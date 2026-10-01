"""Cliente TMDB v3 assíncrono com cache em DuckDB, concorrência limitada e backoff em 429/5xx."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import duckdb
import httpx

BASE_URL = "https://api.themoviedb.org/3"


class NotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TMDB:
    def __init__(self, con: duckdb.DuckDBPyConnection, api_key: str, concurrency: int = 20):
        self.con = con
        # Chave v3 (32 caracteres) vai na query; token de leitura v4 vai no header.
        if len(api_key) > 40:
            headers, params = {"Authorization": f"Bearer {api_key}"}, {}
        else:
            headers, params = {}, {"api_key": api_key}
        self.client = httpx.AsyncClient(base_url=BASE_URL, headers=headers, params=params, timeout=30)
        self.sem = asyncio.Semaphore(concurrency)
        self.calls = 0
        self.cache_hits = 0

    async def __aenter__(self) -> TMDB:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.aclose()

    @staticmethod
    def cache_key(path: str, params: dict) -> str:
        return f"{path}?{urlencode(sorted(params.items()))}"

    async def get(self, path: str, ttl_days: float, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        key = self.cache_key(path, params)
        row = self.con.execute(
            "SELECT payload FROM http_cache WHERE key = ? AND fetched_at > ?",
            [key, _now() - timedelta(days=ttl_days)],
        ).fetchone()
        if row:
            self.cache_hits += 1
            return json.loads(row[0])
        data = await self.fetch(path, params)
        self.con.execute("INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?)", [key, _now(), json.dumps(data)])
        return data

    async def fetch(self, path: str, params: dict, retries: int = 6) -> dict:
        """Requisição sem cache."""
        async with self.sem:
            for attempt in range(retries):
                try:
                    r = await self.client.get(path, params=params)
                except httpx.TransportError:
                    await asyncio.sleep(min(2**attempt, 30) * (0.5 + random.random()))
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    retry_after = r.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else min(2**attempt, 30) * (0.5 + random.random())
                    await asyncio.sleep(wait)
                    continue
                if r.status_code == 404:
                    raise NotFound(path)
                r.raise_for_status()
                self.calls += 1
                return r.json()
        raise RuntimeError(f"TMDB {path} falhou após {retries} tentativas")
