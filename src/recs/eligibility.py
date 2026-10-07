"""Elegibilidade global, independente de afinidade e de provedores."""


def build(con, cfg):
    s = cfg["score"]
    con.execute("""
        CREATE OR REPLACE TEMP TABLE eligibility AS
        SELECT c.tmdb_id, c.exempt OR (
            coalesce(m.vote_count, 0) >= $votes
            AND ($shorts OR coalesce(m.runtime, 0) = 0 OR m.runtime >= $runtime)
            AND ($docs OR NOT EXISTS (SELECT 1 FROM film_genres g
                WHERE g.tmdb_id = c.tmdb_id AND g.genre_id = 99))
        ) AS eligible
        FROM candidates c JOIN film_meta m USING (tmdb_id)
    """, {"votes": s["min_vote_count"], "shorts": s["include_shorts"],
          "runtime": s["min_runtime"], "docs": s["include_documentaries"]})
