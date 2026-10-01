"""Relatório Markdown das recomendações."""

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
        return ", ".join(parts)
    return "aluguel/compra" if a.rent_buy else "—"


def _escape(s: str) -> str:
    return (s or "").replace("|", "\\|")


def section(title: str, rows: list[dict]) -> list[str]:
    lines = [f"## {title}", "", "| # | tmdb | filme | ano | diretor | país | score | motivos | onde |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append("| " + " | ".join([
            str(i), str(r["tmdb_id"]), _escape(title_cell(r)), str(r["year"] or ""), _escape(r["directors"]), r["countries"] or "",
            f"{r['score']:.2f}", _escape(reasons_text(r["reasons"])), _escape(providers_text(r["availability"])),
        ]) + " |")
    return lines + [""]


def write(path: Path, available: list[dict], explore: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Recomendações — {date.today()}",
        "",
        f"Perfil: {meta['profile_films']} filmes · candidatos: {meta['candidates']} "
        f"({meta['eligible']} elegíveis) · provedores assinados em **negrito** · 📌 = watchlist · "
        "`recs feedback <tmdb> bom|nao|ja_vi` para avaliar",
        "",
        *section("Disponível no streaming BR", available),
        *section("Para explorar", explore),
        ATTRIBUTION,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
