from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

import time

from recs import (availability as avail_mod, candidates as cand_mod, config, db, enrich as enrich_mod,
                  ingest as ingest_mod, match as match_mod, profile as profile_mod, report as report_mod,
                  score as score_mod)
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


@app.command()
def enrich():
    """Baixa metadados TMDB dos filmes do Letterboxd (vistos + watchlist), com cache de 90 dias."""
    cfg = config.load()
    con = db.connect()
    ids = [r[0] for r in con.execute("SELECT DISTINCT tmdb_id FROM film_map WHERE tmdb_id IS NOT NULL").fetchall()]

    async def run():
        async with TMDB(con, config.tmdb_key(), cfg["tmdb"]["concurrency"]) as tmdb:
            st = await enrich_mod.fetch_movies(con, tmdb, ids, cfg["tmdb"]["metadata_ttl_days"],
                                              region=cfg["availability"]["region"])
            return st, tmdb.calls

    t0 = time.perf_counter()
    with console.status(f"Enriquecendo {len(ids)} filmes..."):
        st, calls = asyncio.run(run())
        enrich_mod.derive(con)
    console.print(f"[bold]Filmes:[/] {st.requested} · em cache: {st.cached} · baixados: {st.fetched} · "
                  f"requisições: {calls} · {time.perf_counter() - t0:.1f}s")
    if st.not_found:
        console.print(f"[yellow]404 no TMDB:[/] {st.not_found}")

    t = Table(title="Tabelas derivadas")
    for c in ("tabela", "linhas", "filmes"):
        t.add_column(c, justify="right" if c != "tabela" else "left")
    for name in ("film_meta", "film_genres", "film_keywords", "film_countries", "film_languages",
                 "film_people", "film_links"):
        n, f = con.execute(f"SELECT count(*), count(DISTINCT tmdb_id) FROM {name}").fetchone()
        t.add_row(name, str(n), str(f))
    console.print(t)
    for role, n in con.execute(
        "SELECT role, count(DISTINCT tmdb_id) FROM film_people GROUP BY role ORDER BY 2 DESC"
    ).fetchall():
        console.print(f"  {role}: {n} filmes")
    gaps = con.execute("""
        SELECT count(*) FILTER (runtime IS NULL OR runtime = 0), count(*) FILTER (vote_count < 20),
               (SELECT count(*) FROM film_meta m WHERE NOT EXISTS (SELECT 1 FROM film_keywords k WHERE k.tmdb_id = m.tmdb_id))
        FROM film_meta""").fetchone()
    console.print(f"Sem duração: {gaps[0]} · vote_count < 20: {gaps[1]} · sem keywords: {gaps[2]}")


@app.command()
def profile(
    type: list[str] = typer.Option(None, "--type", "-t", help="Tipos a mostrar (padrão: todos)"),
    n: int = typer.Option(15, help="Quantas features no topo"),
    bottom: int = typer.Option(5, help="Quantas features com afinidade mais negativa"),
):
    """Monta o perfil de gosto e imprime o top N por tipo de feature."""
    cfg = config.load()
    con = db.connect()
    feedback = profile_mod.load_feedback(config.root() / "overrides" / "feedback.csv")
    profile_mod.build(con, cfg, feedback=feedback)
    films, rated, mean, liked, wmin, wmax = profile_mod.summary(con)
    console.print(f"[bold]Perfil:[/] {films} filmes · {rated} com nota (média {mean}) · {liked} likes · "
                  f"w ∈ [{wmin}, {wmax}] · k = {cfg['profile']['shrinkage_k']}")
    weights = cfg["profile"]["feature_weights"]
    for ft in type or profile_mod.FEATURE_TYPES:
        t = Table(title=f"{ft} (peso {weights.get(ft)})", title_justify="left", expand=True)
        t.add_column("feature", ratio=2)
        t.add_column("afinidade", justify="right")
        t.add_column("n", justify="right")
        t.add_column("filmes que puxam", ratio=5)
        rows = profile_mod.top(con, ft, n)
        for label, aff, cnt, ex in rows:
            t.add_row(label, f"{aff:+.3f}", str(cnt), ex)
        shown = {r[0] for r in rows}
        worst = [r for r in profile_mod.top(con, ft, bottom, ascending=True) if r[0] not in shown] if bottom else []
        if worst:
            t.add_section()
            for label, aff, cnt, ex in reversed(worst):
                t.add_row(f"[red]{label}[/]", f"[red]{aff:+.3f}[/]", str(cnt), ex)
        console.print(t)


@app.command()
def recommend(n: int = typer.Option(20, help="Quantos filmes por classe")):
    """Gera candidatos, pontua, classifica por disponibilidade no BR e escreve reports/AAAA-MM-DD.md."""
    cfg = config.load()
    root = config.root()
    con = db.connect()
    feedback = profile_mod.load_feedback(root / "overrides" / "feedback.csv")
    profile_mod.build(con, cfg, feedback=feedback)
    exclude = cand_mod.seen_ids(con) | {i for i, v in feedback.items() if v in ("ja_vi", "nao")}
    subscribed = cfg["availability"]["provedores_assinados"]
    t0 = time.perf_counter()

    async def run():
        async with TMDB(con, config.tmdb_key(), cfg["tmdb"]["concurrency"]) as tmdb:
            pool = await cand_mod.generate(con, tmdb, cfg, exclude, root / "seeds")
            cand_mod.save(con, pool)
            st = await enrich_mod.fetch_movies(con, tmdb, list(pool.sources), cfg["tmdb"]["metadata_ttl_days"],
                                              region=cfg["availability"]["region"])
            if st.fetched:
                enrich_mod.derive(con)
                profile_mod.build_film_features(con)
            score_mod.compute(con, cfg)
            meta_calls = tmdb.calls
            # Provedores só para o topo do ranking, com folga para a diversidade e as duas classes.
            top = score_mod.ranked(con, max(15 * n, 300))
            prov = await avail_mod.fetch(con, tmdb, [r["tmdb_id"] for r in top], cfg)
            return pool, st, top, prov, meta_calls, tmdb.calls - meta_calls

    with console.status("Gerando recomendações..."):
        pool, st, top, prov, meta_calls, prov_calls = asyncio.run(run())

    for r in top:
        r["availability"] = avail_mod.classify(prov.get(r["tmdb_id"]), subscribed)
    max_dir = cfg["score"]["max_per_director"]
    available = score_mod.diversify([r for r in top if r["availability"].available], n, max_dir)
    explore = score_mod.diversify([r for r in top if not r["availability"].available], n, max_dir)
    for r in available + explore:
        r["reasons"] = score_mod.reasons(con, r["tmdb_id"])

    src_counts = Counter(s.split(":")[0] if s.startswith("seed") else s for srcs in pool.sources.values() for s in srcs)
    eligible = con.execute("SELECT count(*) FILTER (eligible), count(*) FROM scores").fetchone()
    console.print(f"[bold]Candidatos:[/] {len(pool.sources)} · elegíveis: {eligible[0]} · por fonte: "
                  + ", ".join(f"{k} {v}" for k, v in src_counts.most_common()))
    console.print(f"Enriquecimento: {st.cached} em cache, {st.fetched} baixados · requisições de metadados: "
                  f"{meta_calls} · de provedores: {prov_calls} · {time.perf_counter() - t0:.1f}s")

    for title, rows in (("Disponível no streaming BR", available), ("Para explorar", explore)):
        t = Table(title=title, title_justify="left", expand=True)
        for c, kw in (("#", {"justify": "right"}), ("filme", {"ratio": 3}), ("ano", {}), ("diretor", {"ratio": 2}),
                      ("score", {"justify": "right"}), ("motivos", {"ratio": 4}), ("onde", {"ratio": 2})):
            t.add_column(c, **kw)
        for i, r in enumerate(rows, 1):
            a = r["availability"]
            where = ", ".join(f"[bold green]{p}[/]" if p in a.subscribed else p for p in a.streaming)                 if a.available else ("aluguel/compra" if a.rent_buy else "—")
            t.add_row(str(i), report_mod.title_cell(r), str(r["year"] or ""), r["directors"] or "",
                      f"{r['score']:.2f}", report_mod.reasons_text(r["reasons"]), where)
        console.print(t)

    path = root / "reports" / f"{date.today()}.md"
    report_mod.write(path, available, explore, {
        "profile_films": profile_mod.summary(con)[0], "candidates": len(pool.sources), "eligible": eligible[0]})
    console.print(f"Relatório: {path.relative_to(root)}")
    console.print(report_mod.ATTRIBUTION)


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
