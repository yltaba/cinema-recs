"""Contrato usado pelo Codex, com banco e arquivos isolados e sem rede."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import duckdb
import pytest
from typer.testing import CliRunner

from recs import cli, saved
from recs.db import SCHEMA
from recs.enrich import derive


@pytest.fixture
def local_cli(tmp_path, monkeypatch):
    con = duckdb.connect()
    con.execute(SCHEMA)
    for i in (1, 2):
        data = {"id": i, "title": f"Filme {i}", "original_title": f"Filme {i}",
                "release_date": "2000-01-01", "runtime": 90, "original_language": "pt",
                "genres": [{"id": 35, "name": "Comedy"}, {"id": 10749, "name": "Romance"}],
                "keywords": {"keywords": [{"id": 10, "name": "romantic comedy"}]},
                "credits": {"crew": []}}
        con.execute("INSERT INTO tmdb_raw VALUES (?, now(), ?)", [i, json.dumps(data)])
    derive(con)
    monkeypatch.setattr(cli.db, "connect", lambda: con)
    monkeypatch.setattr(cli.config, "root", lambda: tmp_path)
    monkeypatch.setattr(cli.config, "load", lambda: {
        "availability": {"provedores_assinados": ["Netflix"], "region": "BR"},
        "tmdb": {"concurrency": 1, "metadata_ttl_days": 90},
        "now": {"n": 5, "prefer_bonus": 0.25}, "score": {"max_per_director": 2}})
    monkeypatch.setattr(cli.config, "tmdb_key", lambda: "SYNTHETIC_KEY")
    monkeypatch.setattr(cli.TMDB, "fetch", AsyncMock(side_effect=AssertionError("Rede proibida no teste")))
    yield CliRunner(), tmp_path, con
    con.close()


def invoke_json(runner, args):
    result = runner.invoke(cli.app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    assert not result.stderr
    packet = json.loads(result.stdout)
    assert packet["schema_version"] == 1
    return packet


def test_save_deduplicates_and_feedback_removes_pending(local_cli, monkeypatch):
    runner, root, _ = local_cli
    packet = invoke_json(runner, ["salvar", "1", "1", "2", "--contexto", "comédia romântica"])
    assert packet["salvos"] == [1, 2]
    assert invoke_json(runner, ["salvar", "1"])["ja_salvos"] == [1]
    assert saved.load(root / "overrides/salvos.csv")[1]["contexto"] == "comédia romântica"
    packet = invoke_json(runner, ["feedback", "1", "bom"])
    assert packet["tmdb_id"] == 1 and packet["veredito"] == "bom"
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={
        2: {"flatrate": [{"provider_name": "Netflix"}]}}))
    packet = invoke_json(runner, ["salvos"])
    assert [f["tmdb_id"] for f in packet["filmes"]] == [2]
    assert packet["filmes"][0]["assinados"] == ["Netflix"]
    assert packet["total_salvos"] == 2
    assert "JustWatch" in packet["atribuicao"]


def test_empty_saved_and_keyword_lookup(local_cli):
    runner, _, _ = local_cli
    assert invoke_json(runner, ["salvos"])["filmes"] == []
    assert invoke_json(runner, ["keywords", "romantic"])["keywords"] == [
        {"nome": "romantic comedy", "filmes": 2}]
    assert invoke_json(runner, ["keywords", "inexistente"])["keywords"] == []


def test_invalid_feedback_does_not_write(local_cli):
    runner, root, _ = local_cli
    result = runner.invoke(cli.app, ["feedback", "1", "talvez", "--json"])
    assert result.exit_code != 0
    assert not (root / "overrides/feedback.csv").exists()


def test_now_empty_preserves_constraints_and_warns(local_cli, monkeypatch):
    runner, _, _ = local_cli
    captured = []
    monkeypatch.setattr(cli.profile_mod, "build", lambda *a, **kw: None)
    monkeypatch.setattr(cli.cand_mod, "generate", AsyncMock(return_value=SimpleNamespace(sources={})))
    monkeypatch.setattr(cli.cand_mod, "save", lambda *a: None)
    monkeypatch.setattr(cli.context_mod, "discover", AsyncMock(return_value=set()))
    monkeypatch.setattr(cli.enrich_mod, "fetch_movies", AsyncMock(return_value=SimpleNamespace(fetched=0)))
    monkeypatch.setattr(cli.score_mod, "compute", lambda *a: None)
    monkeypatch.setattr(cli.context_mod, "matching", lambda con, ctx, *a: captured.append(ctx) or {})
    monkeypatch.setattr(cli.score_mod, "ranked", lambda *a, **kw: [])
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={}))
    packet = invoke_json(runner, ["now", "-g", "comedia", "-g", "romance", "--all-genres",
                                  "--max-runtime", "90", "--subscribed-only", "--exclude", "1"])
    assert packet["filmes"] == [] and packet["avisos"]
    assert "JustWatch" in packet["atribuicao"]
    ctx = captured[0]
    assert ctx.genres == [35, 10749] and ctx.all_genres
    assert ctx.max_runtime == 90 and ctx.subscribed_only
