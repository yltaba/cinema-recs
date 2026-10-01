from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from recs import config, db, ingest as ingest_mod, match as match_mod
from recs.tmdb import TMDB

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Recomendador pessoal de filmes.")
console = Console()


@app.command()
def ingest(export: Path = typer.Argument(..., help="ZIP do export do Letterboxd ou pasta descompactada")):
    """Descompacta o export e carrega os CSVs em lb_films."""
    raw = config.root() / "data" / "raw"
    ingest_mod.unpack(export, raw)
    films, stats = ingest_mod.build(raw)
    con = db.connect()
    ingest_mod.load(con, films)

    t = Table(title="Arquivos lidos")
    t.add_column("arquivo")
    t.add_column("linhas", justify="right")
    for k, v in stats.counts.items():
        t.add_row(k, str(v))
    console.print(t)
    s = con.execute(
        """SELECT count(*), count(*) FILTER (watched), count(rating), count(*) FILTER (in_watchlist),
                  count(*) FILTER (liked), count(review_text), count(last_logged), round(avg(rating), 2)
           FROM lb_films"""
    ).fetchone()
    console.print(
        f"[bold]lb_films:[/] {s[0]} filmes · {s[1]} vistos · {s[2]} com nota (média {s[7]}) · "
        f"{s[3]} na watchlist · {s[4]} likes · {s[5]} com resenha · {s[6]} com data"
    )
    if stats.orphans:
        console.print(f"[yellow]{len(stats.orphans)} entradas de diário/resenha sem filme correspondente:[/] "
                      + ", ".join(stats.orphans[:10]))


@app.command()
def match():
    """Resolve tmdb_id de cada filme; grava overrides/unmatched.csv com os não resolvidos."""
    cfg = config.load()
    root = config.root()
    con = db.connect()
    overrides = match_mod.load_overrides(root / "overrides" / "matches.csv")

    async def run():
        async with TMDB(con, config.tmdb_key(), cfg["tmdb"]["concurrency"]) as tmdb:
            res = await match_mod.match_all(con, tmdb, cfg, overrides)
            return res, tmdb.calls, tmdb.cache_hits

    with console.status("Buscando no TMDB..."):
        results, calls, hits = asyncio.run(run())

    unmatched_path = root / "overrides" / "unmatched.csv"
    match_mod.write_unmatched(unmatched_path, results)

    methods = Counter(m.method for _, m in results)
    auto = [(f, m) for f, m in results if not m.method.startswith("override")]
    auto_ok = sum(1 for _, m in auto if m.tmdb_id)
    t = Table(title="Métodos de match")
    t.add_column("método")
    t.add_column("n", justify="right")
    for k, v in methods.most_common():
        t.add_row(k, str(v))
    console.print(t)

    def rate(rows):
        ok = sum(1 for _, m in rows if m.tmdb_id)
        return f"{ok}/{len(rows)} ({100 * ok / max(len(rows), 1):.1f}%)"

    console.print(f"[bold]Automático:[/] {rate(auto)}  ·  vistos: {rate([x for x in auto if x[0]['watched']])}"
                  f"  ·  watchlist: {rate([x for x in auto if x[0]['in_watchlist']])}")
    console.print(f"Requisições TMDB: {calls} · cache: {hits}")

    review_below = cfg["match"]["review_below"]
    ambiguous = sorted(((f, m) for f, m in auto if m.tmdb_id and m.confidence < review_below),
                       key=lambda x: x[1].confidence)
    unmatched = [(f, m) for f, m in results if m.method == "unmatched"]

    if ambiguous:
        t = Table(title=f"Ambíguos (aceitos, confiança < {review_below})")
        for c in ("filme", "ano", "tmdb", "título TMDB", "método", "conf."):
            t.add_column(c)
        titles = _tmdb_titles(con)
        for f, m in ambiguous:
            title, year = titles.get(m.tmdb_id, ("?", "?"))
            t.add_row(f["name"], str(f["year"]), str(m.tmdb_id), f"{title} ({year})", m.method, f"{m.confidence:.2f}")
        console.print(t)
    if unmatched:
        t = Table(title="Não resolvidos → overrides/unmatched.csv")
        for c in ("filme", "ano", "visto", "candidatos"):
            t.add_column(c)
        for f, m in unmatched:
            cands = "; ".join(f'{r["id"]} {r.get("title")} ({match_mod.release_year(r)}) {s:.2f}'
                              for s, r in m.candidates) or "—"
            t.add_row(f["name"], str(f["year"]), "sim" if f["watched"] else "", cands)
        console.print(t)

    _write_match_report(root / "reports" / f"{date.today()}-match.md", results, ambiguous, unmatched, auto_ok, len(auto))


def _tmdb_titles(con) -> dict[int, tuple[str, str]]:
    """Título/ano de cada id a partir das buscas em cache (sem novas requisições)."""
    out: dict[int, tuple[str, str]] = {}
    for (payload,) in con.execute(
        "SELECT payload FROM http_cache WHERE key LIKE '/search/movie?%'"
    ).fetchall():
        for r in json.loads(payload).get("results", []):
            out.setdefault(r["id"], (r.get("title"), (r.get("release_date") or "")[:4]))
    return out


def _write_match_report(path: Path, results, ambiguous, unmatched, auto_ok, auto_n) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Matching Letterboxd → TMDB ({date.today()})",
        "",
        f"Resolvidos automaticamente: **{auto_ok}/{auto_n} ({100 * auto_ok / max(auto_n, 1):.1f}%)**",
        "",
        "## Ambíguos",
        "",
        "| filme | ano | tmdb_id | método | confiança |",
        "|---|---|---|---|---|",
        *(f"| {f['name']} | {f['year']} | {m.tmdb_id} | {m.method} | {m.confidence:.2f} |" for f, m in ambiguous),
        "",
        "## Não resolvidos",
        "",
        "| filme | ano | candidatos |",
        "|---|---|---|",
        *(
            f"| {f['name']} | {f['year']} | "
            + "; ".join(f'{r["id"]} {r.get("title")} ({match_mod.release_year(r)}) {s:.2f}' for s, r in m.candidates)
            + " |"
            for f, m in unmatched
        ),
        "",
        "Dados de filmes: TMDB. Dados de streaming: JustWatch.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
