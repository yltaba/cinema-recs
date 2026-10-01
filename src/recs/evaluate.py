"""Eval offline por holdout.

Para cada seed: esconde uma fração dos filmes com nota alta, refaz perfil e candidatos como se eles não
tivessem sido vistos e mede se o pipeline os traria de volta.

    recall_candidatos = |holdout ∩ pool| / |holdout|
    hit@k             = |holdout ∩ top k| / |holdout|     (top k elegível, com o limite por diretor)
    votos_top20       = mediana de vote_count do top 20   (quão mainstream o ranking ficou)
"""

from __future__ import annotations

import copy
import json
import random
import statistics
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime

import duckdb

from recs import candidates as cand_mod, enrich as enrich_mod, profile as profile_mod, score as score_mod

METRICS = ("cand_recall", "hit20", "hit50", "median_votes_top20")


@dataclass
class SeedResult:
    seed: int
    n_holdout: int
    cand_recall: float
    hit20: float
    hit50: float
    median_votes_top20: float
    fetched: int = 0


def apply_overrides(cfg: dict, sets: list[str]) -> dict:
    """`score.popularity_alpha=0.3` → cópia do config com o valor trocado (valor em sintaxe TOML)."""
    cfg = copy.deepcopy(cfg)
    for s in sets:
        path, _, raw = s.partition("=")
        *parents, leaf = path.strip().split(".")
        node = cfg
        for p in parents:
            node = node[p]
        if leaf not in node:
            raise KeyError(f"chave inexistente no config: {path.strip()}")
        node[leaf] = tomllib.loads(f"v = {raw.strip()}")["v"]
    return cfg


def holdout_ids(con: duckdb.DuckDBPyConnection, min_rating: float, frac: float, seed: int) -> list[int]:
    ids = sorted(r[0] for r in con.execute("""
        SELECT f.tmdb_id FROM lb_films l JOIN film_map f USING (lb_uri)
        WHERE l.watched AND f.tmdb_id IN (SELECT tmdb_id FROM film_meta)
        GROUP BY f.tmdb_id HAVING avg(l.rating) >= ?""", [min_rating]).fetchall())
    return sorted(random.Random(seed).sample(ids, max(1, round(len(ids) * frac))))


async def run_seed(con: duckdb.DuckDBPyConnection, tmdb, cfg: dict, seed: int, frac: float) -> SeedResult:
    hidden = set(holdout_ids(con, cfg["eval"]["min_rating"], frac, seed))
    # Sem feedback: o eval mede o que o histórico do Letterboxd sozinho recupera.
    profile_mod.build(con, cfg, exclude=hidden)
    pool = await cand_mod.generate(con, tmdb, cfg, cand_mod.seen_ids(con) - hidden)
    cand_mod.save(con, pool)
    st = await enrich_mod.fetch_movies(con, tmdb, list(pool.sources), cfg["tmdb"]["metadata_ttl_days"],
                                      region=cfg["availability"]["region"])
    if st.fetched:
        enrich_mod.derive(con)
        profile_mod.build_film_features(con)
    score_mod.compute(con, cfg)
    top = score_mod.diversify(score_mod.ranked(con, 2000), 50, cfg["score"]["max_per_director"])
    ids = [r["tmdb_id"] for r in top]
    return SeedResult(
        seed=seed,
        n_holdout=len(hidden),
        cand_recall=len(hidden & set(pool.sources)) / len(hidden),
        hit20=len(hidden & set(ids[:20])) / len(hidden),
        hit50=len(hidden & set(ids[:50])) / len(hidden),
        median_votes_top20=statistics.median(r["vote_count"] or 0 for r in top[:20]) if top else 0.0,
        fetched=st.fetched,
    )


def summarize(results: list[SeedResult]) -> dict[str, tuple[float, float]]:
    out = {}
    for m in METRICS:
        xs = [getattr(r, m) for r in results]
        out[m] = (statistics.mean(xs), statistics.stdev(xs) if len(xs) > 1 else 0.0)
    return out


def save(con: duckdb.DuckDBPyConnection, label: str, frac: float, cfg: dict, results: list[SeedResult]) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            run_at TIMESTAMP, label TEXT, holdout DOUBLE, seed INTEGER, n_holdout INTEGER,
            cand_recall DOUBLE, hit20 DOUBLE, hit50 DOUBLE, median_votes_top20 DOUBLE, config JSON)""")
    now = datetime.now()
    rows = [{"label": label, "holdout": frac, "cfg": cfg, **asdict(r)} for r in results]
    con.execute("""
        INSERT INTO eval_runs
        SELECT ?::TIMESTAMP, r->>'label', (r->>'holdout')::DOUBLE, (r->>'seed')::INTEGER,
               (r->>'n_holdout')::INTEGER, (r->>'cand_recall')::DOUBLE, (r->>'hit20')::DOUBLE,
               (r->>'hit50')::DOUBLE, (r->>'median_votes_top20')::DOUBLE, r->'cfg'
        FROM (SELECT unnest(json_extract(?::JSON, '$[*]')) AS r)""", [now, json.dumps(rows)])


def previous(con: duckdb.DuckDBPyConnection, frac: float, label: str | None = None
             ) -> tuple[str, dict[str, float]] | None:
    """Médias da última execução com o mesmo holdout (e o rótulo, se dado) para o comparativo."""
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'eval_runs'").fetchone()[0]:
        return None
    row = con.execute("""
        SELECT run_at, any_value(label), avg(cand_recall), avg(hit20), avg(hit50), avg(median_votes_top20)
        FROM eval_runs WHERE holdout = ? AND (? IS NULL OR label = ?)
        GROUP BY run_at ORDER BY run_at DESC LIMIT 1""", [frac, label, label]).fetchone()
    if not row:
        return None
    return f"{row[1] or '(sem rótulo)'} @ {row[0]:%Y-%m-%d %H:%M}", dict(zip(METRICS, row[2:]))
