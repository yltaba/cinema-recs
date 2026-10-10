"""Relatórios Markdown: indicações de cada consulta e revisão do matching."""

from __future__ import annotations

from datetime import date
from pathlib import Path

ATTRIBUTION = "Dados de filmes: TMDB. Dados de streaming: JustWatch."


def title_cell(r: dict) -> str:
    t = r["title"]
    if r["original_title"] and r["original_title"] != t:
        t += f" ({r['original_title']})"
    if "watchlist" in (r["sources"] or []):
        t += " 📌"
    return t


def reasons_text(reasons: list[tuple[str, str, float]]) -> str:
    return " · ".join(f"{t}: {label}" for t, label, _ in reasons)


def providers_text(a) -> str:
    if a.available:
        parts = [f"**{p}**" if p in a.subscribed else p for p in a.streaming]
        text = ", ".join(parts)
        return text + " · também aluguel/compra" if a.rent_buy else text
    if a.rent_buy:
        return "só aluguel/compra"
    return "sem oferta conhecida" if a.known else "sem dado de disponibilidade"


def month_dir(reports: Path, day: date | None = None) -> Path:
    """Relatórios ficam em reports/AAAA/AAAA-MM/, pelo mês em que o comando rodou."""
    day = day or date.today()
    return reports / f"{day:%Y}" / f"{day:%Y-%m}"


def place(path: Path, reports: Path) -> Path:
    """Um arquivo pedido direto em reports/ vai para a pasta do mês; outros caminhos são respeitados."""
    if path.resolve().parent == reports.resolve():
        return month_dir(reports) / path.name
    return path


def unique_path(path: Path) -> Path:
    """Nunca sobrescreve: um relatório pode ter sido editado à mão. Acrescenta -2, -3..."""
    if not path.exists():
        return path
    i = 2
    while (candidate := path.with_name(f"{path.stem}-{i}{path.suffix}")).exists():
        i += 1
    return candidate


def _film(i: int, r: dict) -> list[str]:
    facts = [r["directors"] or "diretor desconhecido",
             f"{r['runtime']} min" if r["runtime"] else "duração desconhecida"]
    if r.get("genres"):
        facts.append(", ".join(r["genres"]))
    if r.get("countries"):
        facts.append(r["countries"])
    why = reasons_text(r["reasons"]) or "—"
    if r.get("prefer_hits"):
        why += " · keywords preferidas: " + ", ".join(r["prefer_hits"])
    year = f" — {r['year']}" if r["year"] else ""
    return [
        f"### {i}. {title_cell(r)}{year}",
        "",
        f"- {' · '.join(facts)}",
        f"- **Onde:** {providers_text(r['availability'])}",
        f"- **Por quê:** {why}",
        f"- score pessoal {r['base']:.2f} · score {r['context_score']:.2f} · "
        f"[tmdb {r['tmdb_id']}](https://www.themoviedb.org/movie/{r['tmdb_id']})",
        "",
    ]


def write_explore(path: Path, rows: list[dict], diagnostic: dict, meta: dict) -> Path:
    """Grava as indicações de uma consulta; devolve o caminho efetivo (ver unique_path)."""
    path = unique_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    main = [r for r in rows if not r.get("origin_complement")]
    complements = [r for r in rows if r.get("origin_complement")]
    lines = [
        f"# Recomendações — {meta['contexto']}",
        "",
        f"- **Data:** {date.today()} · **comando:** `recs {meta['mode']}` · "
        f"**interaction_id:** `{meta['interaction_id']}`",
        f"- **Pool:** {diagnostic['retrieved']} candidatos · {diagnostic['eligible']} elegíveis · "
        f"{diagnostic['context_matched']} passam nos filtros",
        "- Score ordena; não é probabilidade de gostar. 📌 = watchlist · serviços assinados em **negrito**.",
        f"- Disponibilidade do cache TMDB/JustWatch em {date.today()}; pode ter mudado.",
        "",
        "## Indicações",
        "",
    ]
    for i, r in enumerate(main, 1):
        lines += _film(i, r)
    if complements:
        lines += ["## De outros lugares", "",
                  "Acrescentados para que nenhum país passe do teto de origem da lista.", ""]
        for i, r in enumerate(complements, len(main) + 1):
            lines += _film(i, r)
    if meta.get("warnings"):
        lines += ["## Avisos", "", *(f"- {w}" for w in meta["warnings"]), ""]
    lines += ["## Notas", "", "<!-- Comentários, vereditos e revisões com o agente. -->", "", ATTRIBUTION, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_match_review(path: Path, ambiguous, unmatched, titles: dict[int, tuple[str, str]]) -> bool:
    """Lista o que pede revisão humana. Sem pendências, remove o arquivo e devolve False."""
    if not (ambiguous or unmatched):
        path.unlink(missing_ok=True)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Revisão do matching Letterboxd → TMDB",
        "",
        f"Gerado por `recs match` em {date.today()}; reescrito a cada execução e removido quando não há pendências.",
        "Para corrigir, acrescente a linha em `overrides/matches.csv` (`lb_uri,name,year,tmdb_id,note`); "
        "`tmdb_id` vazio ou 0 ignora o filme.",
        "",
    ]
    if ambiguous:
        lines += ["## Ambíguos (aceitos com baixa confiança)", "",
                  "| filme | ano | escolhido no TMDB | método | confiança |", "|---|---|---|---|---|"]
        for f, m in ambiguous:
            title, year = titles.get(m.tmdb_id, ("?", "?"))
            lines.append(f"| {f['name']} | {f['year']} | [{title} ({year})](https://www.themoviedb.org/movie/{m.tmdb_id})"
                         f" · {m.tmdb_id} | {m.method} | {m.confidence:.2f} |")
        lines.append("")
    if unmatched:
        lines += ["## Não resolvidos", "", "Também em `overrides/unmatched.csv`.", "",
                  "| filme | ano | candidatos |", "|---|---|---|"]
        for f, m in unmatched:
            cands = "; ".join(f'{r["id"]} {r.get("title")} ({(r.get("release_date") or "")[:4]}) {s:.2f}'
                              for s, r in m.candidates) or "—"
            lines.append(f"| {f['name']} | {f['year']} | {cands} |")
        lines.append("")
    lines += ["Dados de filmes: TMDB.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return True
