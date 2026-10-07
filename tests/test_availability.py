import asyncio
from unittest.mock import AsyncMock

import pytest

from recs import availability
from recs.context import Context


@pytest.mark.parametrize("limit,expected,reason", [(10, [4, 5], "filled"), (3, [], "limit"),
                                                  (10, [4], "exhausted")])
def test_progressive_selection(monkeypatch, limit, expected, reason):
    rows = [dict(tmdb_id=i, score=10-i, director_ids=[i]) for i in range(1, 6 if reason != "exhausted" else 5)]
    calls = []

    async def fetch(con, tmdb, ids, cfg):
        calls.append(ids)
        return {i: {"flatrate": [{"provider_name": "Netflix"}]} for i in ids if i >= 4}

    monkeypatch.setattr(availability, "fetch", fetch)
    cfg = {"availability": {"batch_size": 2, "max_candidates": limit, "provedores_assinados": ["Netflix"]},
           "score": {"max_per_director": 2}}
    selected, diagnostic = asyncio.run(availability.select(None, None, rows, cfg, Context(subscribed_only=True), 2))
    assert [r["tmdb_id"] for r in selected] == expected
    assert diagnostic["stop_reason"] == reason
    assert diagnostic["checked"] == sum(map(len, calls)) <= limit
    assert all(len(c) <= 2 for c in calls)


def test_batches_continue_until_diversity_is_satisfied(monkeypatch):
    rows = [dict(tmdb_id=i, director_ids=[1 if i < 4 else 2]) for i in range(1, 5)]
    monkeypatch.setattr(availability, "fetch", AsyncMock(return_value={
        i: {"free": [{"provider_name": "Other"}]} for i in range(1, 5)}))
    cfg = {"availability": {"batch_size": 2, "max_candidates": 10, "provedores_assinados": []},
           "score": {"max_per_director": 1}}
    selected, diagnostic = asyncio.run(availability.select(None, None, rows, cfg, Context(streaming_only=True), 2))
    assert [r["tmdb_id"] for r in selected] == [1, 4]
    assert diagnostic["batches"] == 2


def test_unknown_availability_preserves_unrestricted_selection(monkeypatch):
    fetch = AsyncMock(return_value={})
    monkeypatch.setattr(availability, "fetch", fetch)
    cfg = {"availability": {"max_candidates": 1, "provedores_assinados": []},
           "score": {"max_per_director": 2}}
    rows = [dict(tmdb_id=i, score=10-i, director_ids=[]) for i in range(5)]
    selected, diagnostic = asyncio.run(availability.select(None, None, rows, cfg, Context(), 3))
    assert [r["tmdb_id"] for r in selected] == [0, 1, 2]
    assert [r["score"] for r in selected] == [10, 9, 8]
    assert all(not r["availability"].known for r in selected)
    assert diagnostic["checked"] == 3


def test_exact_provider_filter_continues_past_other_subscriptions_and_channels(monkeypatch):
    names = ["MUBI", "Netflix Amazon Channel", "Netflix Standard with Ads"]
    monkeypatch.setattr(availability, "fetch", AsyncMock(return_value={
        i: {"flatrate": [{"provider_name": name}]} for i, name in enumerate(names)}))
    rows = [dict(tmdb_id=i, director_ids=[]) for i in range(3)]
    cfg = {"availability": {"batch_size": 1, "provedores_assinados": ["Netflix", "MUBI"]},
           "score": {"max_per_director": 2}}
    selected, diagnostic = asyncio.run(availability.select(None, None, rows, cfg, Context(providers=["Netflix"]), 1))
    assert [r["tmdb_id"] for r in selected] == [2]
    assert diagnostic["batches"] == 3
