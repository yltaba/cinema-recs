"""Perfil de gosto: peso por filme visto e afinidade por feature com shrinkage.

    w(filme)        = nota − média_do_usuário   (sem nota: unrated_weight; like: + liked_bonus)
    afinidade(feat) = Σw / (n + k)              (keywords: × idf normalizado sobre os filmes do perfil)
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb

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
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {int(r["tmdb_id"]): r["veredito"].strip() for r in csv.DictReader(f) if r.get("tmdb_id")}


def build(con: duckdb.DuckDBPyConnection, cfg: dict, exclude: set[int] | None = None,
          feedback: dict[int, str] | None = None) -> None:
    """Cria profile_films (tmdb_id, w) e profile_features. `exclude` serve ao holdout do eval."""
    p = cfg["profile"]
    build_film_features(con)
    good = [i for i, v in (feedback or {}).items() if v == "bom"]
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
             * CASE WHEN feature_type = 'keyword' THEN ln(N / count(*)) / ln(N) ELSE 1 END AS affinity,
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
