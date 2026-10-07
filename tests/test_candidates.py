import asyncio
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import duckdb

from recs import candidates, context


def test_sources_survive_deduplication_and_storage():
    pool = candidates.Pool()
    for source in ("similar", "recommendations", "discover:profile:country:JP", "watchlist"):
        pool.add(1, source)
    pool.add(1, "similar")
    with duckdb.connect() as con:
        candidates.save(con, pool)
        assert con.execute("SELECT sources FROM candidates").fetchone()[0] == sorted(pool.sources[1])
    assert candidates.source_counts(pool)["similar"] == 1


def test_profile_discover_uses_supported_positive_features_with_evidence():
    with duckdb.connect() as con:
        con.execute("CREATE TABLE profile_features(feature_type TEXT, feature_id TEXT, affinity DOUBLE, n INT)")
        con.execute("INSERT INTO profile_features VALUES ('country','JP',0.5,3), ('language','ja',0.4,1),"
                    "('genre','27',-0.5,5), ('director','1',1.0,10)")
        results = candidates.profile_discover_contexts(con, {})
        assert len(results) == 1
        assert results[0][0] == "discover:profile:country:JP"
        assert results[0][1].countries == ["JP"]
        assert not results[0][1].streaming_only and not results[0][1].subscribed_only


def test_profile_discover_counts_matching_country_and_language_as_one_origin():
    with duckdb.connect() as con:
        con.execute("CREATE TABLE profile_features(feature_type TEXT, feature_id TEXT, affinity DOUBLE, n INT)")
        con.execute("INSERT INTO profile_features VALUES ('country','JP',0.74,6), ('language','ja',0.74,6),"
                    "('language','cn',0.65,3), ('country','HK',0.47,7), ('language','fr',0.48,16)")
        sources = [s for s, _ in candidates.profile_discover_contexts(con, {})]
    assert sources == ["discover:profile:country:JP", "discover:profile:language:cn",
                       "discover:profile:language:fr"]


def test_general_discover_does_not_fetch_provider_list():
    cfg = {"availability": {"region": "BR", "provedores_assinados": ["Netflix"]},
           "now": {"discover_min_votes": 50, "discover_quality_votes": 300, "discover_pages": 1},
           "tmdb": {"search_ttl_days": 90, "providers_ttl_days": 7}}
    tmdb = AsyncMock()
    tmdb.get.return_value = {"results": [{"id": 1}], "total_pages": 1}
    assert asyncio.run(context.discover(tmdb, context.Context(), cfg, general=True)) == {1}
    assert all(c.args[0] == "/discover/movie" for c in tmdb.get.call_args_list)
    assert all(not any("watch" in k for k in c.kwargs) for c in tmdb.get.call_args_list)


def test_generate_unions_sources_and_excludes_seen_after_discover(tmp_path, monkeypatch):
    from recs.db import SCHEMA
    cfg = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
    tmdb = AsyncMock()
    async def get(path, *args, **kwargs):
        if path.startswith("/person/"):
            return {"crew": [{"id": 7, "job": "Director", "vote_count": 100, "release_date": "2000-01-01"}]}
        assert path == "/discover/movie"
        assert not any("watch" in key for key in kwargs)
        return {"results": [{"id": 8}, {"id": 1}], "total_pages": 1}
    tmdb.get.side_effect = get
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "curated.csv").write_text("name,year\nSeed,2000\n", encoding="utf-8")
    monkeypatch.setattr(candidates.match_mod, "resolve", AsyncMock(return_value=SimpleNamespace(tmdb_id=6)))
    candidates.saved_mod.add(tmp_path / "overrides/salvos.csv", [(5, "Saved")])
    with duckdb.connect() as con:
        con.execute(SCHEMA)
        con.execute("CREATE TABLE profile_films(tmdb_id INT, rating DOUBLE)")
        con.execute("INSERT INTO profile_films VALUES (1,5)")
        con.execute("CREATE TABLE profile_features(feature_type TEXT, feature_id TEXT, label TEXT, affinity DOUBLE, n INT)")
        con.execute("INSERT INTO profile_features VALUES ('director','10','Director',0.5,3), ('country','JP','Japan',0.4,2)")
        item = {"id": 2, "vote_count": 100, "release_date": "2000-01-01"}
        payload = {"recommendations": {"results": [item]}, "similar": {"results": [item, {**item, "id": 3}]}}
        con.execute("INSERT INTO tmdb_raw VALUES (1, now(), ?)", [json.dumps(payload)])
        con.execute("INSERT INTO lb_films(lb_uri, watched, in_watchlist) VALUES ('u4', false, true)")
        con.execute("INSERT INTO film_map VALUES ('u4',4,'exact',1)")
        pool = asyncio.run(candidates.generate(con, tmdb, cfg, {1, 3}, seeds))
        assert set(pool.sources) == {2, 4, 5, 6, 7, 8}
        assert pool.sources[2] == {"recommendations", "similar"}
        assert pool.sources[8] == {"discover:profile:country:JP"}
        assert pool.exempt == {4, 5, 6}
        cfg["availability"]["provedores_assinados"] = ["Completely different catalog"]
        other = asyncio.run(candidates.generate(con, tmdb, cfg, {1, 3}, seeds))
        assert other.sources == pool.sources
