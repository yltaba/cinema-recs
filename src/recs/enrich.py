"""Enriquecimento: uma chamada /movie/{id} por filme (com append_to_response), cache em tmdb_raw
e derivação das tabelas normalizadas por SQL sobre o JSON bruto."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import duckdb

from recs.tmdb import TMDB, NotFound

APPEND = "credits,keywords,recommendations,similar,watch/providers"

# job do TMDB → papel usado no perfil
CREW_ROLES = {
    "Director": "director",
    "Screenplay": "writer",
    "Writer": "writer",
    "Story": "writer",
    "Director of Photography": "cinematographer",
    "Editor": "editor",
    "Original Music Composer": "composer",
    "Music": "composer",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class EnrichStats:
    requested: int = 0
    cached: int = 0
    fetched: int = 0
    not_found: list[int] = field(default_factory=list)


async def fetch_movies(con: duckdb.DuckDBPyConnection, tmdb: TMDB, ids: list[int], ttl_days: float,
                       language: str = "pt-BR") -> EnrichStats:
    stats = EnrichStats(requested=len(ids))
    fresh = {
        r[0] for r in con.execute(
            "SELECT tmdb_id FROM tmdb_raw WHERE fetched_at > ?", [_now() - timedelta(days=ttl_days)]
        ).fetchall()
    }
    todo = [i for i in ids if i not in fresh]
    stats.cached = len(ids) - len(todo)

    async def one(tmdb_id: int) -> None:
        try:
            data = await tmdb.fetch(f"/movie/{tmdb_id}", {"append_to_response": APPEND, "language": language})
        except NotFound:
            stats.not_found.append(tmdb_id)
            return
        con.execute("INSERT OR REPLACE INTO tmdb_raw VALUES (?, ?, ?)", [tmdb_id, _now(), json.dumps(data)])
        stats.fetched += 1

    await asyncio.gather(*(one(i) for i in todo))
    return stats


def derive(con: duckdb.DuckDBPyConnection) -> None:
    """Recria as tabelas normalizadas a partir de tmdb_raw (barato; roda sempre inteiro)."""
    roles = ", ".join(f"('{job}', '{role}')" for job, role in CREW_ROLES.items())
    con.execute(f"""
    CREATE OR REPLACE TABLE film_meta AS
    SELECT tmdb_id,
           payload->>'title'                          AS title,
           payload->>'original_title'                 AS original_title,
           TRY_CAST(payload->>'release_date' AS DATE) AS release_date,
           year(TRY_CAST(payload->>'release_date' AS DATE)) AS year,
           (payload->>'runtime')::INTEGER             AS runtime,
           payload->>'original_language'              AS original_language,
           (payload->>'vote_count')::INTEGER          AS vote_count,
           (payload->>'vote_average')::DOUBLE         AS vote_average,
           (payload->>'popularity')::DOUBLE           AS popularity,
           payload->>'imdb_id'                        AS imdb_id,
           payload->>'overview'                       AS overview,
           fetched_at
    FROM tmdb_raw;

    CREATE OR REPLACE TABLE film_genres AS
    SELECT tmdb_id, (g->>'id')::INTEGER AS genre_id, g->>'name' AS name
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.genres[*]')) AS g FROM tmdb_raw);

    CREATE OR REPLACE TABLE film_keywords AS
    SELECT tmdb_id, (k->>'id')::INTEGER AS keyword_id, k->>'name' AS name
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.keywords.keywords[*]')) AS k FROM tmdb_raw);

    CREATE OR REPLACE TABLE film_countries AS
    SELECT tmdb_id, c->>'iso_3166_1' AS iso, c->>'name' AS name
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.production_countries[*]')) AS c FROM tmdb_raw);

    CREATE OR REPLACE TABLE film_languages AS
    SELECT tmdb_id, payload->>'original_language' AS iso, TRUE AS is_original FROM tmdb_raw
    UNION ALL
    SELECT tmdb_id, iso, FALSE FROM (
        SELECT tmdb_id, payload->>'original_language' AS orig,
               unnest(json_extract(payload, '$.spoken_languages[*]'))->>'iso_639_1' AS iso
        FROM tmdb_raw) WHERE iso <> orig;

    CREATE OR REPLACE TABLE film_people AS
    SELECT DISTINCT c.tmdb_id, (c.p->>'id')::INTEGER AS person_id, c.p->>'name' AS name, r.role
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.credits.crew[*]')) AS p FROM tmdb_raw) c
    JOIN (VALUES {roles}) r(job, role) ON c.p->>'job' = r.job;

    CREATE OR REPLACE TABLE film_links AS
    SELECT tmdb_id, (x->>'id')::INTEGER AS related_id, 'recommendation' AS kind
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.recommendations.results[*]')) AS x FROM tmdb_raw)
    UNION ALL
    SELECT tmdb_id, (x->>'id')::INTEGER, 'similar'
    FROM (SELECT tmdb_id, unnest(json_extract(payload, '$.similar.results[*]')) AS x FROM tmdb_raw);
    """)
