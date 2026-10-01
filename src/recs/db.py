from __future__ import annotations

import duckdb

from recs import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS lb_films (
    lb_uri       TEXT PRIMARY KEY,
    name         TEXT,
    year         INTEGER,
    rating       DOUBLE,
    watched      BOOLEAN,
    in_watchlist BOOLEAN,
    liked        BOOLEAN,
    review_text  TEXT,
    last_logged  DATE
);
CREATE TABLE IF NOT EXISTS film_map (
    lb_uri       TEXT PRIMARY KEY,
    tmdb_id      INTEGER,
    match_method TEXT,
    confidence   DOUBLE
);
CREATE TABLE IF NOT EXISTS tmdb_raw (
    tmdb_id    INTEGER PRIMARY KEY,
    fetched_at TIMESTAMP,
    payload    JSON
);
CREATE TABLE IF NOT EXISTS http_cache (
    key        TEXT PRIMARY KEY,
    fetched_at TIMESTAMP,
    payload    JSON
);
"""


def connect() -> duckdb.DuckDBPyConnection:
    path = config.root() / "data" / "recs.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con
