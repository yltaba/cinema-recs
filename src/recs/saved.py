"""Lista local "para ver" (overrides/salvos.csv): sugestões guardadas a partir do `recs now`/`recommend`.

Funciona como uma watchlist local: os salvos entram sempre como candidatos e recebem o mesmo boost.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

FIELDS = ["tmdb_id", "titulo", "contexto", "data"]


def load(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {int(r["tmdb_id"]): r for r in csv.DictReader(f) if (r.get("tmdb_id") or "").strip()}


def add(path: Path, items: list[tuple[int, str]], contexto: str = "") -> list[int]:
    """Anexa (tmdb_id, título) ainda não salvos; devolve os ids novos."""
    current = load(path)
    new = [(i, t) for i, t in dict(items).items() if i not in current]
    if not new:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if write_header:
            w.writeheader()
        for i, t in new:
            w.writerow({"tmdb_id": i, "titulo": t, "contexto": contexto, "data": date.today().isoformat()})
    return [i for i, _ in new]
