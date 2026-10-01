from __future__ import annotations

import os
import tomllib
from functools import cache
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@cache
def root() -> Path:
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "config.toml").exists():
            return d
    raise SystemExit("config.toml não encontrado: rode o comando dentro de cinema-recs/")


@cache
def load() -> dict:
    with open(root() / "config.toml", "rb") as f:
        return tomllib.load(f)


def tmdb_key() -> str:
    # find_dotenv sobe a partir do cwd, então o .env pode ficar na pasta do projeto ou acima dela.
    load_dotenv(find_dotenv(usecwd=True))
    key = os.environ.get("TMDB_API_KEY")
    if not key:
        raise SystemExit("TMDB_API_KEY ausente no .env")
    return key
