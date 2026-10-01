"""Leitura do export do Letterboxd (ZIP ou pasta já descompactada) para a tabela lb_films.

As URIs de diary.csv e reviews.csv apontam para a *entrada* do diário, não para o filme,
então esses arquivos são cruzados por (nome, ano). A chave de lb_films é a URI do filme
que aparece em watched/ratings/watchlist/likes.
"""

from __future__ import annotations

import csv
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb


def unpack(src: Path, raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    if src.is_file() and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            z.extractall(raw)
    elif src.is_dir():
        if src.resolve() != raw.resolve():
            shutil.copytree(src, raw, dirs_exist_ok=True)
    else:
        raise SystemExit(f"{src} não é um ZIP nem uma pasta")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _year(s: str) -> int | None:
    return int(s) if s and s.isdigit() else None


@dataclass
class IngestStats:
    counts: dict[str, int] = field(default_factory=dict)
    orphans: list[str] = field(default_factory=list)  # entradas de diário/resenha sem filme correspondente


def build(raw: Path) -> tuple[list[dict], IngestStats]:
    films: dict[str, dict] = {}
    by_name_year: dict[tuple[str, int | None], str] = {}
    stats = IngestStats()

    def film(r: dict) -> dict:
        uri = r["Letterboxd URI"]
        f = films.get(uri)
        if f is None:
            f = films[uri] = dict(
                lb_uri=uri, name=r["Name"], year=_year(r["Year"]), rating=None, watched=False,
                in_watchlist=False, liked=False, review_text=None, last_logged=None,
            )
            by_name_year[(f["name"], f["year"])] = uri
        return f

    def bump_logged(f: dict, d: str | None) -> None:
        if d and (f["last_logged"] is None or d > f["last_logged"]):
            f["last_logged"] = d

    for r in (rows := read_csv(raw / "watched.csv")):
        f = film(r)
        f["watched"] = True
        bump_logged(f, r["Date"])
    stats.counts["watched"] = len(rows)

    for r in (rows := read_csv(raw / "ratings.csv")):
        f = film(r)
        f["watched"] = True
        f["rating"] = float(r["Rating"]) if r["Rating"] else None
    stats.counts["ratings"] = len(rows)

    for r in (rows := read_csv(raw / "watchlist.csv")):
        film(r)["in_watchlist"] = True
    stats.counts["watchlist"] = len(rows)

    for r in (rows := read_csv(raw / "likes" / "films.csv")):
        film(r)["liked"] = True
    stats.counts["likes"] = len(rows)

    def lookup(r: dict) -> dict | None:
        uri = by_name_year.get((r["Name"], _year(r["Year"])))
        if uri is None:
            stats.orphans.append(f'{r["Name"]} ({r["Year"]})')
            return None
        return films[uri]

    for r in (rows := read_csv(raw / "diary.csv")):
        if f := lookup(r):
            bump_logged(f, r.get("Watched Date") or r["Date"])
    stats.counts["diary"] = len(rows)

    for r in sorted(rows := read_csv(raw / "reviews.csv"), key=lambda r: r["Date"]):
        if (f := lookup(r)) and r["Review"].strip():
            text = r["Review"].strip()
            f["review_text"] = f"{f['review_text']}\n\n{text}" if f["review_text"] else text
    stats.counts["reviews"] = len(rows)

    return list(films.values()), stats


COLUMNS = ["lb_uri", "name", "year", "rating", "watched", "in_watchlist", "liked", "review_text", "last_logged"]


def load(con: duckdb.DuckDBPyConnection, films: list[dict]) -> None:
    con.execute("DELETE FROM lb_films")
    con.executemany(
        f"INSERT INTO lb_films ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [[f[c] for c in COLUMNS] for f in films],
    )
