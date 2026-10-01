"""Disponibilidade no Brasil (dados JustWatch via TMDB) e classificação disponível × explorar."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import duckdb

STREAM_TYPES = ("flatrate", "free", "ads")
PAID_TYPES = ("rent", "buy")


@dataclass
class Availability:
    streaming: list[str] = field(default_factory=list)   # flatrate/free/ads
    subscribed: list[str] = field(default_factory=list)  # subconjunto de streaming que o usuário assina
    rent_buy: bool = False

    @property
    def available(self) -> bool:
        return bool(self.streaming)


AD_TIER = re.compile(r"( Standard)? with Ads$", re.IGNORECASE)


def base_name(provider: str) -> str:
    """'Netflix Standard with Ads' → 'Netflix'. Canais ('MUBI Amazon Channel') continuam distintos:
    são assinaturas à parte, não o serviço em si."""
    return AD_TIER.sub("", provider).strip()


def is_subscribed(provider: str, subscribed: list[str]) -> bool:
    return base_name(provider).lower() in {s.lower() for s in subscribed}


def classify(region_data: dict | None, subscribed: list[str]) -> Availability:
    a = Availability()
    if not region_data:
        return a
    seen = set()
    for t in STREAM_TYPES:
        for p in region_data.get(t, []):
            name = base_name(p["provider_name"])
            if name not in seen:
                seen.add(name)
                a.streaming.append(name)
    a.subscribed = [n for n in a.streaming if is_subscribed(n, subscribed)]
    a.streaming = a.subscribed + [n for n in a.streaming if n not in a.subscribed]
    a.rent_buy = any(region_data.get(t) for t in PAID_TYPES)
    return a


async def fetch(con: duckdb.DuckDBPyConnection, tmdb, ids: list[int], cfg: dict) -> dict[int, dict | None]:
    """Provedores na região. Usa o que veio no enriquecimento se ainda estiver dentro do TTL de provedores;
    senão consulta /watch/providers (cache próprio de 7 dias)."""
    region, ttl = cfg["availability"]["region"], cfg["tmdb"]["providers_ttl_days"]
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=ttl)
    out: dict[int, dict | None] = {}
    for tid, data in con.execute(
        f"""SELECT tmdb_id, json_extract(payload, '$."watch/providers".results.{region}')
            FROM tmdb_raw WHERE fetched_at > ? AND tmdb_id IN (SELECT unnest(?::INTEGER[]))""",
        [cutoff, ids],
    ).fetchall():
        out[tid] = json.loads(data) if data else None

    async def one(tid: int) -> None:
        data = await tmdb.get(f"/movie/{tid}/watch/providers", ttl)
        out[tid] = data.get("results", {}).get(region)

    await asyncio.gather(*(one(t) for t in ids if t not in out))
    return out
