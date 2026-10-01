"""Geração de candidatos: união deduplicada de várias fontes, sem filmes já vistos.

Um pré-filtro barato (vote_count e data de lançamento, que já vêm nas listas do TMDB) evita
enriquecer milhares de filmes que o score descartaria de qualquer forma.
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from recs import match as match_mod, saved as saved_mod

# papel no perfil → jobs aceitos na filmografia
FILMOGRAPHY_JOBS = {
    "director": {"Director"},
    "cinematographer": {"Director of Photography"},
    "writer": {"Screenplay", "Writer", "Story"},
}


@dataclass
class Pool:
    sources: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    exempt: set[int] = field(default_factory=set)  # watchlist/seeds: não passam pelo pré-filtro

    def add(self, tmdb_id: int, source: str) -> None:
        self.sources[tmdb_id].add(source)


def _passes(item: dict, min_votes: int, today: str) -> bool:
    rd = item.get("release_date") or ""
    return not item.get("adult") and (item.get("vote_count") or 0) >= min_votes and rd != "" and rd <= today


def seen_ids(con: duckdb.DuckDBPyConnection) -> set[int]:
    return {r[0] for r in con.execute(
        "SELECT f.tmdb_id FROM lb_films l JOIN film_map f USING (lb_uri) WHERE l.watched AND f.tmdb_id IS NOT NULL"
    ).fetchall()}


async def generate(con: duckdb.DuckDBPyConnection, tmdb, cfg: dict, exclude: set[int],
                   seeds_dir: Path | None = None) -> Pool:
    c, min_votes, today = cfg["candidates"], cfg["score"]["min_vote_count"], date.today().isoformat()
    pool = Pool()

    # 1. recommendations + similar dos filmes com nota alta (já estão no payload enriquecido)
    seed_ids = [r[0] for r in con.execute(
        "SELECT tmdb_id FROM profile_films WHERE rating >= ?", [c["seed_min_rating"]]).fetchall()]
    for (payload,) in con.execute(
        "SELECT payload FROM tmdb_raw WHERE tmdb_id IN (SELECT unnest(?::INTEGER[]))", [seed_ids]
    ).fetchall():
        p = json.loads(payload)
        for kind in ("recommendations", "similar"):
            for item in (p.get(kind) or {}).get("results", []):
                if _passes(item, min_votes, today):
                    pool.add(item["id"], kind)

    # 2–3. filmografias dos top diretores, fotógrafos e roteiristas. "affinity" ordena pela média
    # encolhida; "total" pela evidência acumulada Σw = afinidade·(n + k), que favorece quem tem vários
    # filmes bons em vez de um único 5★.
    order = {"affinity": "affinity",
             "total": f"affinity * (n + {float(cfg['profile']['shrinkage_k'])})"}[c.get("people_rank", "affinity")]
    people: list[tuple[int, str, str]] = []
    for role, key in (("director", "top_directors"), ("cinematographer", "top_cinematographers"),
                      ("writer", "top_writers")):
        people += [(int(pid), role, label) for pid, label in con.execute(
            f"SELECT feature_id, label FROM profile_features WHERE feature_type = ? AND affinity > 0 "
            f"ORDER BY {order} DESC, n DESC, feature_id LIMIT ?", [role, c[key]]).fetchall()]

    async def filmography(pid: int, role: str) -> list[dict]:
        data = await tmdb.get(f"/person/{pid}/movie_credits", cfg["tmdb"]["metadata_ttl_days"], language="en-US")
        return [x for x in data.get("crew", []) if x.get("job") in FILMOGRAPHY_JOBS[role]]

    credits = await asyncio.gather(*(filmography(pid, role) for pid, role, _ in people))
    for (pid, role, label), items in zip(people, credits):
        for item in items:
            if _passes(item, min_votes, today):
                pool.add(item["id"], f"filmografia:{role}")

    # 4. watchlist do Letterboxd: sempre entra
    for (tid,) in con.execute(
        "SELECT f.tmdb_id FROM lb_films l JOIN film_map f USING (lb_uri) "
        "WHERE l.in_watchlist AND NOT l.watched AND f.tmdb_id IS NOT NULL").fetchall():
        pool.add(tid, "watchlist")
        pool.exempt.add(tid)

    # 5. salvos localmente (overrides/salvos.csv): sempre entram, como a watchlist
    if seeds_dir:
        for tid in saved_mod.load(seeds_dir.parent / "overrides" / "salvos.csv"):
            pool.add(tid, "salvo")
            pool.exempt.add(tid)

    # 6. listas curadas (seeds/*.csv com Name,Year ou name,year)
    if seeds_dir and seeds_dir.exists():
        for path in sorted(seeds_dir.glob("*.csv")):
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = [{k.lower(): v for k, v in r.items()} for r in csv.DictReader(f)]
            found = await asyncio.gather(*(
                match_mod.resolve(tmdb, r["name"], int(r["year"]) if (r.get("year") or "").isdigit() else None, cfg)
                for r in rows if r.get("name")))
            for m in found:
                if m.tmdb_id:
                    pool.add(m.tmdb_id, f"seed:{path.stem}")
                    pool.exempt.add(m.tmdb_id)

    for tid in list(pool.sources):
        if tid in exclude:
            del pool.sources[tid]
    return pool


def save(con: duckdb.DuckDBPyConnection, pool: Pool) -> None:
    con.execute("CREATE OR REPLACE TABLE candidates (tmdb_id INTEGER PRIMARY KEY, sources TEXT[], exempt BOOLEAN)")
    if pool.sources:
        # Um único parâmetro JSON: executemany ou listas Python como parâmetro levam ~1 min para alguns
        # milhares de linhas (o DuckDB tenta importar numpy/pandas a cada valor convertido).
        rows = [{"id": i, "src": sorted(src), "ex": i in pool.exempt} for i, src in pool.sources.items()]
        con.execute("""
            INSERT INTO candidates
            SELECT (r->>'id')::INTEGER, json_extract_string(r, '$.src[*]'), (r->>'ex')::BOOLEAN
            FROM (SELECT unnest(json_extract(?::JSON, '$[*]')) AS r)""", [json.dumps(rows)])
