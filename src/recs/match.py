"""Resolução Letterboxd (nome + ano) → tmdb_id."""

from __future__ import annotations

import asyncio
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz
from unidecode import unidecode

# Artigos iniciais removidos na normalização (en, pt, es, fr, it, de).
ARTICLES = {
    "the", "a", "an",
    "o", "os", "as", "um", "uma",
    "el", "los", "las", "un", "una",
    "le", "la", "les", "une",
    "il", "lo", "gli",
    "der", "die", "das", "ein", "eine",
}


def normalize(title: str) -> str:
    s = unidecode(title).lower().replace("&", " and ")
    s = re.sub(r"^l'", "", s)  # L'Avventura, L'Argent
    s = re.sub(r"[^\w\s]", " ", s)
    words = s.split()
    if len(words) > 1 and words[0] in ARTICLES:
        words = words[1:]
    return " ".join(words)


def release_year(r: dict) -> int | None:
    d = r.get("release_date") or ""
    return int(d[:4]) if d[:4].isdigit() else None


def title_sim(name: str, r: dict) -> float:
    n = normalize(name)
    titles = {t for t in (r.get("title"), r.get("original_title")) if t}
    return max((fuzz.ratio(n, normalize(t)) / 100 for t in titles), default=0.0)


def year_sim(year: int | None, r: dict) -> float:
    ry = release_year(r)
    if year is None or ry is None:
        return 0.5
    return {0: 1.0, 1: 0.8, 2: 0.4}.get(abs(year - ry), 0.0)


def score(name: str, year: int | None, r: dict) -> float:
    return 0.7 * title_sim(name, r) + 0.3 * year_sim(year, r)


@dataclass
class Match:
    tmdb_id: int | None
    method: str
    confidence: float
    candidates: list[tuple[float, dict]] = field(default_factory=list)  # top 3 para revisão


def choose_strict(name: str, year: int | None, results: list[dict]) -> Match | None:
    """Passo 2: título normalizado idêntico (ano ±1), ou resultado único com ano compatível."""
    exact = [r for r in results if title_sim(name, r) == 1.0 and year_sim(year, r) >= 0.8]
    if exact:
        # Remakes com o mesmo nome: desempata pelo ano e depois pela popularidade.
        exact.sort(key=lambda r: (year_sim(year, r), r.get("vote_count", 0)), reverse=True)
        best = exact[0]
        tied = [r for r in exact[1:] if year_sim(year, r) == year_sim(year, best)]
        # Homônimo no mesmo ano só é ambíguo se não houver um claramente mais conhecido.
        runner_up = max((r.get("vote_count", 0) for r in tied), default=0)
        clear_winner = best.get("vote_count", 0) >= max(5 * runner_up, runner_up + 50)
        conf = 0.85 if tied and not clear_winner else score(name, year, best)
        return Match(best["id"], "exact", conf)
    if len(results) == 1 and year_sim(year, results[0]) >= 0.8:
        # Título traduzido: único resultado no ano costuma ser o filme certo.
        return Match(results[0]["id"], "single", score(name, year, results[0]))
    return None


def choose_fuzzy(name: str, year: int | None, results: list[dict], threshold: float, min_margin: float) -> Match:
    """Passo 3: melhor score combinado no pool ampliado, com limiar e margem sobre o segundo."""
    uniq = {r["id"]: r for r in results}
    ranked = sorted(((score(name, year, r), r) for r in uniq.values()), key=lambda x: x[0], reverse=True)
    top = ranked[:3]
    if not ranked:
        return Match(None, "unmatched", 0.0, top)
    best_s, best = ranked[0]
    second_s = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_s >= threshold and best_s - second_s >= min_margin:
        return Match(best["id"], "fuzzy", best_s, top)
    return Match(None, "unmatched", best_s, top)


async def resolve(tmdb, name: str, year: int | None, cfg: dict) -> Match:
    m = cfg["match"]
    ttl, lang = cfg["tmdb"]["search_ttl_days"], m["search_language"]

    async def search(query: str = name, **params) -> list[dict]:
        data = await tmdb.get("/search/movie", ttl, query=query, language=lang, include_adult="false", **params)
        return data.get("results", [])

    first = await search(year=year)
    if hit := choose_strict(name, year, first):
        return hit

    extra = [first]
    if year:
        extra += await asyncio.gather(
            search(primary_release_year=year - 1), search(primary_release_year=year + 1), search()
        )
    prefix = re.split(r"[:,]", name, maxsplit=1)[0].strip()
    if not any(extra) and prefix != name:
        # Títulos longos com pontuação ("Jeanne Dielman, 23, quai du Commerce...") às vezes não voltam na busca.
        extra += [await search(prefix, year=year), await search(prefix)]
    pool = list({r["id"]: r for rs in extra for r in rs}.values())
    if hit := choose_strict(name, year, pool):
        hit.method += "_widened"
        return hit
    return choose_fuzzy(name, year, pool, m["accept_threshold"], m["min_margin"])


# --- overrides -----------------------------------------------------------------------------

OVERRIDE_FIELDS = ["lb_uri", "name", "year", "tmdb_id", "note"]


def load_overrides(path: Path) -> dict:
    """Chaveado por lb_uri e por (nome, ano). tmdb_id vazio ou 0 = ignorar (ex.: série de TV)."""
    out: dict = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            tid = (r.get("tmdb_id") or "").strip()
            value = int(tid) if tid and tid != "0" else None
            if r.get("lb_uri"):
                out[r["lb_uri"].strip()] = value
            if r.get("name"):
                y = (r.get("year") or "").strip()
                out[(r["name"].strip(), int(y) if y.isdigit() else None)] = value
    return out


async def match_all(con, tmdb, cfg: dict, overrides: dict) -> list[tuple[dict, Match]]:
    films = con.execute(
        "SELECT lb_uri, name, year, watched, rating, in_watchlist FROM lb_films ORDER BY name"
    ).fetchall()
    films = [dict(zip(["lb_uri", "name", "year", "watched", "rating", "in_watchlist"], f)) for f in films]

    async def one(f: dict) -> tuple[dict, Match]:
        for key in (f["lb_uri"], (f["name"], f["year"])):
            if key in overrides:
                tid = overrides[key]
                return f, Match(tid, "override" if tid else "override_skip", 1.0)
        return f, await resolve(tmdb, f["name"], f["year"], cfg)

    results = await asyncio.gather(*(one(f) for f in films))
    con.execute("DELETE FROM film_map")
    con.executemany(
        "INSERT INTO film_map VALUES (?, ?, ?, ?)",
        [[f["lb_uri"], m.tmdb_id, m.method, round(m.confidence, 4)] for f, m in results],
    )
    return results


def write_unmatched(path: Path, results: list[tuple[dict, Match]]) -> None:
    """Mesmo formato de matches.csv: preencher tmdb_id e copiar a linha para lá."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, OVERRIDE_FIELDS)
        w.writeheader()
        for film, m in results:
            if m.method != "unmatched":
                continue
            note = "; ".join(
                f'{r["id"]} {r.get("title")} ({release_year(r)}) {s:.2f}' for s, r in m.candidates
            )
            w.writerow(dict(lb_uri=film["lb_uri"], name=film["name"], year=film["year"], tmdb_id="", note=note))
