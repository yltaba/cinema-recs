"""Perfil de gosto: peso por filme visto e afinidade por feature com shrinkage.

    w(filme)        = nota − média_do_usuário   (sem nota: unrated_weight; like: + liked_bonus)
    afinidade(feat) = Σw / (n + k)              (keywords: × idf normalizado sobre os filmes do perfil)
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from recs import feedback as feedback_mod

FEATURE_TYPES = ["director", "writer", "cinematographer", "editor", "composer",
                 "country", "language", "decade", "keyword", "genre"]


def build_film_features(con: duckdb.DuckDBPyConnection) -> None:
    """Uma linha por (filme, feature). Usada pelo perfil e, na Fase 4, pelo score."""
    con.execute("""
    CREATE OR REPLACE TABLE film_features AS
    SELECT tmdb_id, role AS feature_type, person_id::TEXT AS feature_id, name AS label FROM film_people
    UNION ALL SELECT tmdb_id, 'country', iso, name FROM film_countries
    UNION ALL SELECT tmdb_id, 'language', iso, name FROM film_languages WHERE is_original
    UNION ALL SELECT tmdb_id, 'decade', (year // 10 * 10)::TEXT, (year // 10 * 10)::TEXT || 's'
              FROM film_meta WHERE year IS NOT NULL
    UNION ALL SELECT tmdb_id, 'keyword', keyword_id::TEXT, name FROM film_keywords
    UNION ALL SELECT tmdb_id, 'genre', genre_id::TEXT, name FROM film_genres
    """)


def load_feedback(path: Path) -> dict[int, str]:
    return feedback_mod.load(path)


def build(con: duckdb.DuckDBPyConnection, cfg: dict, exclude: set[int] | None = None,
          feedback: dict[int, str] | None = None) -> None:
    """Cria profile_films (tmdb_id, w) e profile_features. `exclude` serve ao holdout do eval."""
    p = cfg["profile"]
    build_film_features(con)
    good = [i for i, v in (feedback or {}).items() if feedback_mod.normalize(v) == "liked" and i not in (exclude or set())]
    con.execute("""
    CREATE OR REPLACE TABLE profile_films AS
    WITH seen AS (
        SELECT f.tmdb_id, avg(l.rating) AS rating, bool_or(l.liked) AS liked
        FROM lb_films l JOIN film_map f USING (lb_uri)
        WHERE l.watched AND f.tmdb_id IS NOT NULL
          AND f.tmdb_id IN (SELECT tmdb_id FROM film_meta)
          AND f.tmdb_id NOT IN (SELECT unnest($exclude::INTEGER[]))
        GROUP BY f.tmdb_id
    ), mu AS (SELECT avg(rating) AS m FROM seen)
    SELECT tmdb_id, rating, liked,
           coalesce(rating - mu.m, $unrated) + CASE WHEN liked THEN $liked ELSE 0 END AS w
    FROM seen, mu
    UNION ALL
    SELECT tmdb_id, NULL, FALSE, $good_w FROM film_meta
    WHERE tmdb_id IN (SELECT unnest($good::INTEGER[])) AND tmdb_id NOT IN (SELECT tmdb_id FROM seen)
    """, {"exclude": sorted(exclude or []), "unrated": p["unrated_weight"], "liked": p["liked_bonus"],
          "good": good, "good_w": p["feedback_good_weight"]})

    # idf normalizado em [0, 1] sobre os filmes do perfil: keyword presente em todos → 0, em um só → 1.
    con.execute("""
    CREATE OR REPLACE TABLE profile_features AS
    WITH ff AS (
        SELECT ff.*, pf.w FROM film_features ff JOIN profile_films pf USING (tmdb_id)
    ), n_films AS (SELECT count(*)::DOUBLE AS N FROM profile_films)
    SELECT feature_type, feature_id, any_value(label) AS label,
           sum(w) / (count(*) + $k)
             * CASE WHEN feature_type = 'keyword' THEN
                    CASE WHEN N <= 1 THEN 0 ELSE ln(N / count(*)) / ln(N) END
                    ELSE 1 END AS affinity,
           count(*) AS n
    FROM ff, n_films
    GROUP BY feature_type, feature_id, N
    """, {"k": p["shrinkage_k"]})


def summary(con: duckdb.DuckDBPyConnection) -> tuple:
    return con.execute("""
        SELECT count(*), count(rating), round(avg(rating), 2), count(*) FILTER (liked),
               round(min(w), 2), round(max(w), 2)
        FROM profile_films""").fetchone()


def top(con: duckdb.DuckDBPyConnection, feature_type: str, n: int, ascending: bool = False) -> list[tuple]:
    """(label, afinidade, n, até 3 filmes do perfil que mais puxam a feature no mesmo sentido)."""
    order = "ASC" if ascending else "DESC"
    return con.execute(f"""
        WITH sel AS (
            SELECT * FROM profile_features WHERE feature_type = ? ORDER BY affinity {order}, n DESC LIMIT ?
        )
        SELECT s.label, s.affinity, s.n,
               (SELECT string_agg(t, ' · ') FROM (
                    SELECT m.title || ' (' || coalesce(pf.rating::TEXT, '–') || ')' AS t
                    FROM film_features ff JOIN profile_films pf USING (tmdb_id) JOIN film_meta m USING (tmdb_id)
                    WHERE ff.feature_type = s.feature_type AND ff.feature_id = s.feature_id
                    ORDER BY pf.w {order} LIMIT 3)) AS films
        FROM sel s ORDER BY s.affinity {order}, s.n DESC
    """, [feature_type, n]).fetchall()


def explain(con, cfg, types=None, n=15, bottom=5):
    """Afinidades e evidências por ID, sem depender de texto formatado para tabelas."""
    features = []
    for ft in types or FEATURE_TYPES:
        positive = con.execute("SELECT feature_id, label, affinity, n FROM profile_features WHERE feature_type = ? "
                               "ORDER BY affinity DESC, n DESC, feature_id LIMIT ?", [ft, n]).fetchall()
        negative = con.execute("SELECT feature_id, label, affinity, n FROM profile_features WHERE feature_type = ? AND affinity < 0 "
                               "ORDER BY affinity, n DESC, feature_id LIMIT ?", [ft, bottom]).fetchall()
        seen = set()
        for fid, label, affinity, count in positive + negative:
            if fid in seen:
                continue
            seen.add(fid)
            order = "ASC" if affinity < 0 else "DESC"
            evidence = con.execute(f"""
                SELECT DISTINCT pf.tmdb_id, m.title, pf.rating, pf.w
                FROM film_features ff JOIN profile_films pf USING (tmdb_id) JOIN film_meta m USING (tmdb_id)
                WHERE ff.feature_type = ? AND ff.feature_id = ?
                ORDER BY pf.w {order}, pf.tmdb_id LIMIT 3
            """, [ft, fid]).fetchall()
            features.append({"tipo": ft, "id": fid, "nome": label, "afinidade": affinity,
                             "n": count, "peso_tipo": cfg["profile"]["feature_weights"].get(ft, 0),
                             "evidencias": [{"tmdb_id": i, "titulo": t, "nota": rating, "peso_filme": w}
                                            for i, t, rating, w in evidence]})
    films, rated, mean, liked, wmin, wmax = summary(con)
    return {"schema_version": 1, "resumo": {"filmes": films, "avaliados": rated, "media": mean,
            "likes": liked, "peso_min": wmin, "peso_max": wmax}, "features": features,
            "shrinkage_k": cfg["profile"]["shrinkage_k"],
            "semantica": "Afinidade derivada do histórico; streaming não integra o gosto. Score não é probabilidade."}
