"""Vizinhos colaborativos do MovieLens (GroupLens): "quem gostou de X também gostou de Y".

Calculados uma vez, offline, para os filmes do histórico; a geração de candidatos usa os vizinhos dos filmes
com nota alta. Gostar = nota ≥ min_rating. Para cada filme do histórico, amostra até users_per_seed usuários
que gostaram dele (ordem determinística por hash) e estima o cosseno binário

    cos(X, Y) ≈ (co_amostra · n_X / n_amostra) / sqrt(n_X · n_Y)

onde n_X e n_Y contam todos os usuários que gostaram de cada filme. Os dados do MovieLens não saem da máquina.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def _csv(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def build(con: duckdb.DuckDBPyConnection, ml_dir: Path, cfg: dict) -> dict:
    """Recria ml_neighbors (tmdb_id, neighbor_id, score, support) para os filmes vistos."""
    ratings, links = ml_dir / "ratings.csv", ml_dir / "links.csv"
    for f in (ratings, links):
        if not f.exists():
            raise FileNotFoundError(f"{f.name} não encontrado em {ml_dir}")
    m = cfg["movielens"]
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ml_links AS
        SELECT movieId, tmdbId FROM read_csv('{_csv(links)}', header = true,
            columns = {{'movieId': 'INTEGER', 'imdbId': 'VARCHAR', 'tmdbId': 'INTEGER'}})
        WHERE tmdbId IS NOT NULL""")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ml_liked AS
        SELECT userId, movieId FROM read_csv('{_csv(ratings)}', header = true,
            columns = {{'userId': 'INTEGER', 'movieId': 'INTEGER', 'rating': 'DOUBLE', 'timestamp': 'BIGINT'}})
        WHERE rating >= $min_rating""", {"min_rating": m["min_rating"]})
    con.execute("""
        CREATE OR REPLACE TEMP TABLE ml_seeds AS
        SELECT DISTINCT k.movieId FROM ml_links k JOIN film_map f ON f.tmdb_id = k.tmdbId
        JOIN lb_films l USING (lb_uri) WHERE l.watched""")
    con.execute("""
        CREATE OR REPLACE TABLE ml_neighbors AS
        WITH item_n AS (SELECT movieId, count(*) AS n FROM ml_liked GROUP BY movieId),
        sampled AS (
            SELECT s.movieId AS seed, l.userId FROM ml_seeds s JOIN ml_liked l USING (movieId)
            QUALIFY row_number() OVER (PARTITION BY s.movieId ORDER BY hash(l.userId), l.userId) <= $users
        ),
        n_sampled AS (SELECT seed, count(*) AS n FROM sampled GROUP BY seed),
        co AS (
            SELECT sp.seed, l.movieId AS nb, count(*) AS co FROM sampled sp JOIN ml_liked l USING (userId)
            WHERE l.movieId <> sp.seed GROUP BY ALL
        ),
        scored AS (
            SELECT co.seed, co.nb, co.co,
                   (co.co::DOUBLE * a.n / ns.n) / sqrt(a.n::DOUBLE * b.n) AS score
            FROM co JOIN n_sampled ns USING (seed)
            JOIN item_n a ON a.movieId = co.seed JOIN item_n b ON b.movieId = co.nb
            WHERE co.co >= $support AND b.n >= $item_likes
            QUALIFY row_number() OVER (PARTITION BY co.seed ORDER BY score DESC, co.nb) <= $keep
        )
        SELECT ks.tmdbId AS tmdb_id, kn.tmdbId AS neighbor_id, max(s.score) AS score, max(s.co) AS support
        FROM scored s JOIN ml_links ks ON ks.movieId = s.seed JOIN ml_links kn ON kn.movieId = s.nb
        WHERE ks.tmdbId <> kn.tmdbId
        GROUP BY ALL""", {"users": m["users_per_seed"], "support": m["min_support"],
                           "item_likes": m["min_item_likes"], "keep": m["neighbors_kept"]})
    stats = con.execute("""
        SELECT (SELECT count(*) FROM ml_seeds), count(DISTINCT tmdb_id), count(*), count(DISTINCT neighbor_id)
        FROM ml_neighbors""").fetchone()
    for t in ("ml_links", "ml_liked", "ml_seeds"):
        con.execute(f"DROP TABLE {t}")
    return dict(zip(("vistos_no_movielens", "com_vizinhos", "pares", "vizinhos_distintos"), stats))


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'ml_neighbors'").fetchone()[0])


def neighbors(con: duckdb.DuckDBPyConnection, seed_ids: list[int], per_seed: int) -> list[int]:
    """Os per_seed vizinhos mais próximos de cada filme semente (vazio sem tabela ou com per_seed = 0)."""
    if per_seed <= 0 or not seed_ids or not available(con):
        return []
    return [r[0] for r in con.execute("""
        SELECT DISTINCT neighbor_id FROM (
            SELECT neighbor_id FROM ml_neighbors WHERE tmdb_id IN (SELECT unnest(?::INTEGER[]))
            QUALIFY row_number() OVER (PARTITION BY tmdb_id ORDER BY score DESC, neighbor_id) <= ?)
        ORDER BY neighbor_id""", [seed_ids, per_seed]).fetchall()]
