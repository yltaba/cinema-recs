"""Metadados de disponibilidade e seleção progressiva quando streaming é obrigatório."""

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
    known: bool = False  # ausência de dados não prova indisponibilidade

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
    a = Availability(known=region_data is not None)
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


async def select(con, tmdb, rows, cfg, ctx, n):
    """Enriquece a seleção; só filtra quando o contexto exige streaming.

    Percorre a ordem recebida em lotes até preencher a seleção com diversidade,
    esgotar o pool ou consumir o orçamento. Nunca modifica scores.
    Sem país ou idioma pedidos, aplica o teto de origem (score.max_country_share): a seleção principal
    fica intacta e recebe complementos de outros países quando um país domina a lista.
    """
    from recs.score import diversify, origin_share

    max_dir = cfg["score"]["max_per_director"]
    cap = 0.0 if (ctx.countries or ctx.languages) else float(cfg["score"].get("max_country_share", 0) or 0)

    def choose(rows):
        return diversify(rows, n, max_dir, cap)

    def balanced(sel):
        return len(sel) >= n and (cap <= 0 or origin_share(sel)[1] <= cap + 1e-9)

    settings = cfg["availability"]
    required = bool(ctx.subscribed_only or ctx.streaming_only or ctx.providers)
    batch_size = settings.get("batch_size", 50)
    limit = settings.get("max_candidates", 1000)
    if n < 1 or batch_size < 1 or limit < 1:
        raise ValueError("n, batch_size e max_candidates devem ser positivos")
    diagnostic = {"required": required, "checked": 0, "matched": 0, "batches": 0}
    # Sem restrição: escolhe antes da consulta, para que catálogo nunca afete a seleção.
    pending = rows[:limit] if required else choose(rows)
    accepted = []
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        providers = await fetch(con, tmdb, [r["tmdb_id"] for r in batch], cfg)
        diagnostic["batches"] += 1
        diagnostic["checked"] += len(batch)
        for original in batch:
            r = dict(original)
            a = classify(providers.get(r["tmdb_id"]), settings["provedores_assinados"])
            r["availability"] = a
            passes = ((not ctx.subscribed_only or bool(a.subscribed))
                      and (not ctx.streaming_only or a.available)
                      and (not ctx.providers or any(is_subscribed(p, ctx.providers)
                                                   for p in (a.subscribed if ctx.subscribed_only else a.streaming))))
            if passes:
                accepted.append(r)
        if balanced(choose(accepted)):
            break
    selected = choose(accepted)
    dominant, share = origin_share(selected)
    diagnostic["matched"] = len(accepted)
    diagnostic["returned"] = len(selected)
    diagnostic["origem"] = {"cap": cap, "dominante": dominant, "participacao": round(share, 3),
                            "complementos": sum(1 for r in selected if r.get("origin_complement"))}
    diagnostic["stop_reason"] = ("filled" if len(selected) >= n else
                                  "limit" if required and len(rows) > limit else "exhausted")
    return selected, diagnostic
