"""Score dos candidatos.

    base  = Σ_tipo peso_tipo × agg(afinidade)       agg = soma (keywords) ou média (pessoas, país, ...)
    score = base × penalidade_pop × boost_watchlist
    penalidade_pop = 1 / (1 + α · log1p(vote_count))
"""

from __future__ import annotations

import duckdb

ROLE_LABELS = {
    "director": "diretor", "writer": "roteiro", "cinematographer": "fotografia", "editor": "montagem",
    "composer": "trilha", "country": "país", "language": "idioma", "decade": "década",
    "keyword": "keyword", "genre": "gênero",
}
DOCUMENTARY_GENRE = 99


def compute(con: duckdb.DuckDBPyConnection, cfg: dict) -> None:
    s, weights = cfg["score"], cfg["profile"]["feature_weights"]
    con.execute("CREATE OR REPLACE TEMP TABLE type_weights (feature_type TEXT, weight DOUBLE)")
    con.executemany("INSERT INTO type_weights VALUES (?, ?)", list(weights.items()))
    # Tipos fora de sum_feature_types entram pela média sobre todas as features daquele tipo no filme
    # (desconhecidas contam 0): uma antologia com 20 diretores não soma 20 afinidades.
    con.execute("""
    CREATE OR REPLACE TABLE contributions AS
    WITH per_type AS (
        SELECT tmdb_id, feature_type, count(*) AS k FROM film_features
        WHERE tmdb_id IN (SELECT tmdb_id FROM candidates) GROUP BY ALL
    )
    SELECT c.tmdb_id, ff.feature_type, ff.feature_id, pf.label, pf.affinity, pf.n,
           tw.weight * pf.affinity
             / CASE WHEN list_contains($sum_types, ff.feature_type) THEN 1 ELSE pt.k END AS contrib
    FROM candidates c
    JOIN film_features ff USING (tmdb_id)
    JOIN per_type pt ON pt.tmdb_id = ff.tmdb_id AND pt.feature_type = ff.feature_type
    JOIN profile_features pf ON pf.feature_type = ff.feature_type AND pf.feature_id = ff.feature_id
    JOIN type_weights tw ON tw.feature_type = ff.feature_type
    """, {"sum_types": s["sum_feature_types"]})
    con.execute("""
    CREATE OR REPLACE TABLE scores AS
    WITH base AS (
        SELECT c.tmdb_id, c.sources, c.exempt, coalesce(sum(ct.contrib), 0) AS base
        FROM candidates c LEFT JOIN contributions ct USING (tmdb_id)
        GROUP BY ALL
    )
    SELECT b.tmdb_id, b.sources, b.base,
           1 / (1 + $alpha * ln(1 + coalesce(m.vote_count, 0))) AS pop_penalty,
           CASE WHEN list_contains(b.sources, 'watchlist') THEN $boost ELSE 1 END AS boost,
           b.base * pop_penalty * boost AS score,
           b.exempt OR (
               coalesce(m.vote_count, 0) >= $min_votes
               AND ($shorts OR coalesce(m.runtime, 0) = 0 OR m.runtime >= $min_runtime)
               AND ($docs OR NOT EXISTS (
                   SELECT 1 FROM film_genres g WHERE g.tmdb_id = b.tmdb_id AND g.genre_id = $doc_genre))
           ) AS eligible
    FROM base b JOIN film_meta m USING (tmdb_id)
    """, {"alpha": s["popularity_alpha"], "boost": cfg["candidates"]["watchlist_boost"],
          "min_votes": s["min_vote_count"], "shorts": s["include_shorts"], "min_runtime": s["min_runtime"],
          "docs": s["include_documentaries"], "doc_genre": DOCUMENTARY_GENRE})


def ranked(con: duckdb.DuckDBPyConnection, limit: int, only: str | None = None) -> list[dict]:
    """Elegíveis por score; `only` restringe aos tmdb_id de uma tabela (ex.: context_ok)."""
    restrict = f"AND s.tmdb_id IN (SELECT tmdb_id FROM {only})" if only else ""
    rows = con.execute(f"""
        SELECT s.tmdb_id, s.score, s.base, s.pop_penalty, s.boost, s.sources,
               m.title, m.original_title, m.year, m.vote_count, m.runtime,
               (SELECT string_agg(name, ', ') FROM film_people p
                 WHERE p.tmdb_id = s.tmdb_id AND p.role = 'director') AS directors,
               (SELECT list(person_id) FROM film_people p
                 WHERE p.tmdb_id = s.tmdb_id AND p.role = 'director') AS director_ids,
               (SELECT string_agg(iso, '/') FROM film_countries c WHERE c.tmdb_id = s.tmdb_id) AS countries
        FROM scores s JOIN film_meta m USING (tmdb_id)
        WHERE s.eligible {restrict}
        ORDER BY s.score DESC
        LIMIT ?""", [limit]).fetchall()
    cols = ["tmdb_id", "score", "base", "pop_penalty", "boost", "sources", "title", "original_title", "year",
            "vote_count", "runtime", "directors", "director_ids", "countries"]
    return [dict(zip(cols, r)) for r in rows]


def reasons(con: duckdb.DuckDBPyConnection, tmdb_id: int, k: int = 3) -> list[tuple[str, str, float]]:
    """As k features com maior contribuição positiva: (tipo, rótulo, contribuição)."""
    return [(ROLE_LABELS[t], label, c) for t, label, c in con.execute("""
        SELECT feature_type, label, contrib FROM contributions
        WHERE tmdb_id = ? AND contrib > 0 ORDER BY contrib DESC LIMIT ?""", [tmdb_id, k]).fetchall()]


def diversify(rows: list[dict], n: int, max_per_director: int) -> list[dict]:
    out, per_director = [], {}
    for r in rows:
        ids = r["director_ids"] or []
        if any(per_director.get(d, 0) >= max_per_director for d in ids):
            continue
        for d in ids:
            per_director[d] = per_director.get(d, 0) + 1
        out.append(r)
        if len(out) == n:
            break
    return out
