from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

import time

from recs import (availability as avail_mod, candidates as cand_mod, config, context as context_mod, db,
                  enrich as enrich_mod, evaluate as eval_mod, historico as historico_mod, ingest as ingest_mod, match as match_mod,
                  movielens as ml_mod,
                  profile as profile_mod, report as report_mod, score as score_mod,
                  pipeline as pipeline_mod, interactions, feedback as feedback_mod, ratings as ratings_mod)
from recs.tmdb import TMDB

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_show_locals=False,
                  help="Recomendador pessoal de filmes.")
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

    titles = _tmdb_titles(con)
    if ambiguous:
        t = Table(title=f"Ambíguos (aceitos, confiança < {review_below})")
        for c in ("filme", "ano", "tmdb", "título TMDB", "método", "conf."):
            t.add_column(c)
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

    review = root / "reports" / "revisao-match.md"
    if report_mod.write_match_review(review, ambiguous, unmatched, titles):
        console.print(f"Revisão em {review.relative_to(root)}")


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


@app.command("movielens")
def movielens_cmd(ml_dir: Path = typer.Argument(..., help="Pasta do MovieLens com ratings.csv e links.csv")):
    """Calcula vizinhos colaborativos dos filmes vistos (ml_neighbors). Refaça após um novo export."""
    cfg = config.load()
    con = db.connect()
    t0 = time.perf_counter()
    try:
        with console.status("Calculando vizinhos..."):
            stats = ml_mod.build(con, ml_dir, cfg)
    except FileNotFoundError as e:
        raise typer.BadParameter(str(e))
    console.print(f"Vistos no MovieLens: {stats['vistos_no_movielens']} · com vizinhos: {stats['com_vizinhos']} · "
                  f"pares: {stats['pares']} · vizinhos distintos: {stats['vizinhos_distintos']} · "
                  f"{time.perf_counter() - t0:.1f}s")
    if not cfg["candidates"].get("movielens_per_seed"):
        console.print("[yellow]candidates.movielens_per_seed = 0: a fonte está desligada no config.[/]")


@app.command()
def profile(
    type: list[str] = typer.Option(None, "--type", "-t", help="Tipos a mostrar (padrão: todos)"),
    n: int = typer.Option(15, help="Quantas features no topo"),
    bottom: int = typer.Option(5, help="Quantas features com afinidade mais negativa"),
    as_json: bool = typer.Option(False, "--json", help="Perfil e evidências estruturados"),
):
    """Monta o perfil de gosto e imprime o top N por tipo de feature."""
    cfg = config.load()
    con = db.connect()
    feedback = profile_mod.load_feedback(config.root() / "overrides" / "feedback.csv")
    ratings = ratings_mod.load(config.root() / "overrides" / "avaliacoes.csv")
    profile_mod.build(con, cfg, feedback=feedback, ratings=ratings)
    if as_json:
        typer.echo(json.dumps(profile_mod.explain(con, cfg, type, n, bottom), ensure_ascii=False, allow_nan=False))
        return
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
def recommend(cli_context: typer.Context, n: int = typer.Option(20, min=1, help="Quantos filmes")):
    """Compatibilidade: exploração geral com relatório Markdown."""
    now(cli_context=cli_context, n=n, genre=None, all_genres=False, max_runtime=None, min_runtime=None, language=None,
        country=None, years=None, prefer=None, avoid=None, subscribed_only=False,
        streaming_only=False, exclude=None, as_json=False,
        markdown=config.root() / "reports" / f"{date.today()}.md", provider=None)


@app.command("explore")
@app.command()
def now(
    cli_context: typer.Context,
    genre: list[str] = typer.Option(None, "--genre", "-g", help="Gênero(s), pt ou en; vários = qualquer um"),
    all_genres: bool = typer.Option(False, "--all-genres", help="Exige todos os gêneros (comédia + policial)"),
    max_runtime: int = typer.Option(None, help="Duração máxima em minutos"),
    min_runtime: int = typer.Option(None, help="Duração mínima em minutos"),
    language: list[str] = typer.Option(None, help="Idioma original ISO 639-1 (pt, en, ja...)"),
    country: list[str] = typer.Option(None, help="País de produção ISO 3166-1 (BR, FR...)"),
    years: str = typer.Option(None, help="1990s, 1980-2000, 2010-, -1979"),
    prefer: list[str] = typer.Option(None, help="Keywords TMDB que puxam para cima (nome exato; ver `recs keywords`)"),
    avoid: list[str] = typer.Option(None, help="Termos de keyword que eliminam o filme ('gore' pega 'extreme gore')"),
    subscribed_only: bool = typer.Option(False, "--subscribed-only", help="Só nos serviços assinados"),
    streaming_only: bool = typer.Option(False, "--streaming-only", help="Só em streaming no BR (qualquer serviço)"),
    provider: list[str] = typer.Option(None, help="Só nestes serviços, pelo nome exato; vários = qualquer um"),
    exclude: list[str] = typer.Option(None, help="tmdb_ids a pular só nesta consulta"),
    n: int = typer.Option(None, min=1, help="Quantos filmes (padrão: config now.n)"),
    markdown: Path = typer.Option(None, help="Grava também um relatório Markdown neste caminho"),
    as_json: bool = typer.Option(False, "--json", help="Saída JSON para o agente e automação"),
):
    """Recomendações pessoais; filtros opcionais e streaming como metadado por padrão."""
    cfg = config.load()
    root = config.root()
    n = n or cfg["now"]["n"]
    try:
        ctx = context_mod.build(genre, max_runtime, min_runtime, language, country, years, prefer, avoid,
                                subscribed_only, streaming_only, exclude, all_genres, provider)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    con = db.connect()
    feedback = profile_mod.load_feedback(root / "overrides" / "feedback.csv")
    ratings = ratings_mod.load(root / "overrides" / "avaliacoes.csv")
    profile_mod.build(con, cfg, feedback=feedback, ratings=ratings)
    t0 = time.perf_counter()

    async def run():
        async with TMDB(con, config.tmdb_key(), cfg["tmdb"]["concurrency"]) as tmdb:
            rows, diagnostic, warnings = await pipeline_mod.query(con, tmdb, cfg, ctx, n, root, feedback, ratings)
            return rows, diagnostic, warnings, tmdb.calls

    status = contextlib.nullcontext() if as_json else console.status("Buscando...")
    with status:
        rows, diagnostic, warnings, calls = asyncio.run(run())

    interaction_id = interactions.record_query(con, cli_context.info_name,
                                               {**pipeline_mod.structured_context(ctx), "n": n}, rows, diagnostic, cfg)

    report_path = None
    if markdown:
        report_path = report_mod.write_explore(markdown, rows, diagnostic, {
            "contexto": ctx.describe(), "mode": cli_context.info_name, "interaction_id": interaction_id,
            "warnings": warnings})

    if as_json:
        out = {
            "schema_version": 1,
            "interaction_id": interaction_id,
            "contexto": ctx.describe(),
            "consulta": {**pipeline_mod.structured_context(ctx), "n": n},
            "diagnostico": diagnostic,
            "filmes": [{
                "tmdb_id": r["tmdb_id"], "titulo": r["title"], "titulo_original": r["original_title"],
                "ano": r["year"], "diretor": r["directors"], "duracao": r["runtime"], "generos": r["genres"],
                "score_pessoal": round(r["base"], 3), "fontes": r["sources"],
                "score": round(r["score"], 3), "score_contexto": round(r["context_score"], 3),
                "ajustes": {"popularidade": r["pop_penalty"], "watchlist": r["boost"]},
                "motivos": [f"{t}: {label}" for t, label, _ in r["reasons"]],
                "motivos_detalhados": [{"tipo": t, "nome": label, "contribuicao": contribution}
                                        for t, label, contribution in r["reasons"]],
                "keywords_preferidas": r["prefer_hits"],
                "watchlist": "watchlist" in (r["sources"] or []),
                "assinados": r["availability"].subscribed, "streaming": r["availability"].streaming,
                "aluguel_compra": r["availability"].rent_buy,
                "disponibilidade_conhecida": r["availability"].known,
                "complemento_origem": bool(r.get("origin_complement")),
            } for r in rows],
            "avisos": warnings,
            "relatorio": str(report_path) if report_path else None,
            "atribuicao": report_mod.ATTRIBUTION,
        }
        typer.echo(json.dumps(out, ensure_ascii=False, indent=1))
        return

    console.print(f"[bold]Contexto:[/] {ctx.describe()}")
    console.print(f"Pool: {diagnostic['retrieved']} candidatos · {diagnostic['context_matched']} passam nos filtros · "
                  f"requisições: {calls} · {time.perf_counter() - t0:.1f}s")
    t = Table(expand=True)
    for c, kw in (("#", {"justify": "right"}), ("tmdb", {"justify": "right"}), ("filme", {"ratio": 3}), ("ano", {}),
                  ("diretor", {"ratio": 2}), ("min", {"justify": "right"}), ("score", {"justify": "right"}),
                  ("motivos", {"ratio": 4}), ("onde", {"ratio": 2})):
        t.add_column(c, **kw)
    for i, r in enumerate(rows, 1):
        a = r["availability"]
        where = ", ".join(f"[bold green]{p}[/]" if p in a.subscribed else p for p in a.streaming) \
            if a.available else ("aluguel/compra" if a.rent_buy else "—")
        why = report_mod.reasons_text(r["reasons"])
        if r["prefer_hits"]:
            why += " · [cyan]" + ", ".join(r["prefer_hits"]) + "[/]"
        if r.get("origin_complement"):
            why += " · [magenta]de outros lugares[/]"
        t.add_row(str(i), str(r["tmdb_id"]), report_mod.title_cell(r), str(r["year"] or ""), r["directors"] or "",
                  str(r["runtime"] or ""), f"{r['context_score']:.2f}", why, where)
    console.print(t)
    for w in warnings:
        console.print(f"[yellow]{w}[/]")
    if report_path:
        console.print(f"Relatório: {report_path}")
    console.print(report_mod.ATTRIBUTION)


@app.command()
def keywords(term: str = typer.Argument(..., help="Trecho do nome (em inglês)"),
             limit: int = typer.Option(30),
             as_json: bool = typer.Option(False, "--json", help="Saída JSON para o agente e automação")):
    """Keywords do TMDB já em cache que contêm o termo, com o nº de filmes (para --prefer/--avoid)."""
    rows = context_mod.search_keywords(db.connect(), term, limit)
    if as_json:
        typer.echo(json.dumps({"schema_version": 1, "keywords": [
            {"nome": name, "filmes": cnt} for name, cnt in rows]}, ensure_ascii=False))
        return
    for name, cnt in rows:
        console.print(f"{cnt:5d}  {name}")


@app.command("historico")
def historico(titulos: list[str] = typer.Argument(..., help='Títulos, opcionalmente com ano: "Get Out (2017)"'),
              as_json: bool = typer.Option(False, "--json", help="Saída JSON para o agente e automação")):
    """Confere se títulos já estão no histórico: export, feedback ou avaliação privada."""
    root = config.root()
    out = historico_mod.lookup(db.connect(), titulos,
                               profile_mod.load_feedback(root / "overrides" / "feedback.csv"),
                               ratings_mod.load(root / "overrides" / "avaliacoes.csv"))
    if as_json:
        typer.echo(json.dumps({"schema_version": 1, "consultas": out}, ensure_ascii=False))
        return
    for c in out:
        if not c["resultados"]:
            console.print(f"{c['termo']}: não encontrado no histórico")
        for r in c["resultados"]:
            flags = [k for k, on in (("visto", r["visto"]), ("watchlist", r["watchlist"]),
                                     ("like", r["like_letterboxd"])) if on]
            if r["nota_letterboxd"] is not None:
                flags.append(f"nota {r['nota_letterboxd']}")
            if r["feedback"]:
                flags.append(f"feedback {r['feedback']}")
            console.print(f"{c['termo']}: {r['titulo']} ({r['ano']}) · {', '.join(flags) or 'sem status'}")


@app.command("eval")
def eval_(
    holdout: float = typer.Option(None, help="Fração dos filmes com nota alta escondida (padrão: config)"),
    label: str = typer.Option("", help="Rótulo da execução em eval_runs"),
    set_: list[str] = typer.Option(None, "--set", help="Sobrescreve o config só neste eval, ex.: score.popularity_alpha=0.3"),
    vs: str = typer.Option(None, help="Rótulo da execução para comparar (padrão: a última)"),
):
    """Holdout offline: recall de candidatos, hit@20/50 e mediana de votos do top 20, média ± desvio entre seeds."""
    cfg = eval_mod.apply_overrides(config.load(), set_ or [])
    frac = holdout if holdout is not None else cfg["eval"]["holdout"]
    con = db.connect()
    prev = eval_mod.previous(con, frac, vs)
    t0 = time.perf_counter()

    async def run():
        async with TMDB(con, config.tmdb_key(), cfg["tmdb"]["concurrency"]) as tmdb:
            res = [await eval_mod.run_seed(con, tmdb, cfg, s, frac) for s in cfg["eval"]["seeds"]]
            return res, tmdb.calls

    with console.status(f"Avaliando {len(cfg['eval']['seeds'])} seeds..."):
        results, calls = asyncio.run(run())
    eval_mod.save(con, label or ", ".join(set_ or []), frac, cfg, results)

    t = Table(title=f"Holdout {frac:.0%} dos filmes com nota ≥ {cfg['eval']['min_rating']}"
                    + (f" · {', '.join(set_)}" if set_ else ""), title_justify="left")
    for c in ("seed", "escondidos", "recall cand.", "hit@20", "hit@50", "votos top 20"):
        t.add_column(c, justify="right")
    for r in results:
        t.add_row(str(r.seed), str(r.n_holdout), f"{r.cand_recall:.1%}", f"{r.hit20:.1%}", f"{r.hit50:.1%}",
                  f"{r.median_votes_top20:.0f}")
    summ = eval_mod.summarize(results)
    t.add_section()
    t.add_row("média ± dp", "", *(f"{m:.1%} ± {d:.1%}" for m, d in (summ[k] for k in eval_mod.METRICS[:3])),
              "{:.0f} ± {:.0f}".format(*summ["median_votes_top20"]))
    if prev:
        delta = lambda k, fmt: fmt.format(summ[k][0] - prev[1][k])
        t.add_row("Δ", "", *(delta(k, "{:+.1%}") for k in eval_mod.METRICS[:3]),
                  delta("median_votes_top20", "{:+.0f}"))
    console.print(t)
    if prev:
        console.print(f"Comparado com: {prev[0]}")
    for metric in eval_mod.METRICS[4:]:
        mean, std = summ[metric]
        if mean is None:
            console.print(f"{metric}: sem evidência suficiente")
            continue
        delta = f" · Δ {mean - prev[1][metric]:+.3f}" if prev and prev[1].get(metric) is not None else ""
        console.print(f"{metric}: {mean:.3f} ± {std:.3f}{delta}")
    console.print(f"Requisições TMDB: {calls} · {time.perf_counter() - t0:.1f}s · "
                  "tabelas de perfil/candidatos ficaram no estado do último seed; rode `recs recommend` para refazê-las")


VERDICTS = feedback_mod.VERDICTS


@app.command()
def feedback(
    tmdb_id: int = typer.Argument(...),
    veredito: str = typer.Argument(..., help="liked | disliked | not_interested | already_seen | not_now (aliases: bom, nao, ja_vi)"),
    as_json: bool = typer.Option(False, "--json"),
    interaction: str = typer.Option(None),
):
    """Registra feedback persistente ou uma exclusao contextual ligada a interacao."""
    if veredito not in VERDICTS:
        raise typer.BadParameter(f"use um de: {', '.join(VERDICTS)}", param_hint="veredito")
    canonical = feedback_mod.normalize(veredito)
    if canonical == "not_now" and not interaction:
        raise typer.BadParameter("not_now requer --interaction; para busca avulsa use --exclude")
    con = db.connect()
    try:
        interactions.validate_action(con, interaction, [tmdb_id])
    except ValueError as e:
        raise typer.BadParameter(str(e))
    if canonical != "not_now":
        feedback_mod.append(config.root() / "overrides" / "feedback.csv", tmdb_id, canonical)
    interactions.record_action(con, canonical, [tmdb_id], interaction)
    effect = {"liked": "entra no perfil com peso positivo e sai das sugestoes",
              "disliked": "visto; sai das sugestoes, sem aprender afinidade negativa ainda",
              "not_interested": "sai das sugestoes sem alterar afinidades",
              "already_seen": "sai das sugestoes como assistido",
              "not_now": "exclusao somente desta consulta; preserve --exclude no refinamento"}[canonical]
    out = {"schema_version": 1, "tmdb_id": tmdb_id, "veredito": veredito,
           "veredito_canonico": canonical, "efeito": effect, "interaction_id": interaction}
    if canonical == "not_now":
        out["exclude"] = [tmdb_id]
    if as_json:
        typer.echo(json.dumps(out, ensure_ascii=False))
    else:
        console.print(f"{tmdb_id}: {veredito} -> {effect}")


@app.command()
def rate(
    tmdb_id: int = typer.Argument(...),
    nota: float = typer.Option(None, "--nota", help="0,5 a 5, em passos de 0,5"),
    like: bool = typer.Option(False, "--like/--no-like"),
    critica: str = typer.Option(None, "--critica", help="Critica privada, guardada so em overrides/avaliacoes.csv"),
    interaction: str = typer.Option(None),
    as_json: bool = typer.Option(False, "--json"),
):
    """Registra avaliacao privada (nota, like, critica) de um filme assistido."""
    con = db.connect()
    row = con.execute("SELECT title FROM film_meta WHERE tmdb_id = ?", [tmdb_id]).fetchone()
    if not row:
        raise typer.BadParameter("filme desconhecido; ele precisa estar no banco (aparecer numa busca com recs explore/now)", param_hint="tmdb_id")
    if not ratings_mod.valid_rating(nota):
        raise typer.BadParameter("use de 0,5 a 5, em passos de 0,5", param_hint="--nota")
    if not as_json and nota is None and critica is None and sys.stdin.isatty():
        raw = typer.prompt("Nota (0,5 a 5; vazio = sem nota)", default="", show_default=False).replace(",", ".")
        try:
            nota = float(raw) if raw else None
        except ValueError:
            raise typer.BadParameter("nota invalida", param_hint="--nota")
        if not ratings_mod.valid_rating(nota):
            raise typer.BadParameter("use de 0,5 a 5, em passos de 0,5", param_hint="--nota")
        like = typer.confirm("Like?", default=False)
        critica = typer.prompt("Critica privada (vazio = nenhuma)", default="", show_default=False) or None
    try:
        interactions.validate_action(con, interaction, [tmdb_id])
    except ValueError as e:
        raise typer.BadParameter(str(e))
    ratings_mod.append(config.root() / "overrides" / "avaliacoes.csv", tmdb_id, row[0], nota, like, critica, interaction)
    interactions.record_action(con, "rated", [tmdb_id], interaction, {"nota": nota, "like": like})
    effect = "assistido; entra no perfil com a nota privada ate aparecer no export do Letterboxd e sai das sugestoes"
    out = {"schema_version": 1, "tmdb_id": tmdb_id, "titulo": row[0], "nota": nota, "like": like,
           "critica_gravada": bool(critica), "efeito": effect, "interaction_id": interaction}
    if as_json:
        typer.echo(json.dumps(out, ensure_ascii=False))
    else:
        console.print(f"{row[0]} ({tmdb_id}): nota {nota if nota is not None else '-'}{' + like' if like else ''} -> {effect}")


@app.command("ratings")
def ratings_list(
    full: bool = typer.Option(False, "--full", help="Critica completa"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Lista as avaliacoes privadas."""
    items = [{"tmdb_id": i, **r} for i, r in ratings_mod.load(config.root() / "overrides" / "avaliacoes.csv").items()]
    if not full:
        for r in items:
            r["critica"] = r["critica"] if len(r["critica"]) <= 80 else r["critica"][:77] + "..."
    if as_json:
        typer.echo(json.dumps({"schema_version": 1, "avaliacoes": items}, ensure_ascii=False))
        return
    t = Table(title="Avaliacoes privadas")
    for c in ("tmdb_id", "titulo", "nota", "like", "data", "critica"):
        t.add_column(c)
    for r in items:
        t.add_row(str(r["tmdb_id"]), r["titulo"], "-" if r["nota"] is None else str(r["nota"]),
                  "sim" if r["like"] else "", r["data"], r["critica"])
    console.print(t)


@app.command("interaction")
def interaction_show(interaction_id: str, as_json: bool = typer.Option(False, "--json")):
    """Consulta o registro local de uma interacao e suas acoes."""
    try:
        out = {"schema_version": 1, **interactions.get(db.connect(), interaction_id)}
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


def _tmdb_titles(con) -> dict[int, tuple[str, str]]:
    """Título/ano de cada id a partir das buscas em cache (sem novas requisições)."""
    out: dict[int, tuple[str, str]] = {}
    for (payload,) in con.execute(
        "SELECT payload FROM http_cache WHERE key LIKE '/search/movie?%'"
    ).fetchall():
        for r in json.loads(payload).get("results", []):
            out.setdefault(r["id"], (r.get("title"), (r.get("release_date") or "")[:4]))
    return out
