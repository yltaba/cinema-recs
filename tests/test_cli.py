"""Contrato usado pelo agente, com banco e arquivos isolados e sem rede."""

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import duckdb
import pytest
from typer.testing import CliRunner

from recs import cli
from recs.db import SCHEMA
from recs.enrich import derive


@pytest.fixture
def local_cli(tmp_path, monkeypatch):
    con = duckdb.connect()
    con.execute(SCHEMA)
    for i in (1, 2):
        data = {"id": i, "title": f"Filme {i}", "original_title": f"Filme {i}",
                "release_date": "2000-01-01", "vote_count": 100, "runtime": 90, "original_language": "pt",
                "genres": [{"id": 35, "name": "Comedy"}, {"id": 10749, "name": "Romance"}],
                "keywords": {"keywords": [{"id": 10, "name": "romantic comedy"}]},
                "credits": {"crew": []}}
        con.execute("INSERT INTO tmdb_raw VALUES (?, now(), ?)", [i, json.dumps(data)])
    derive(con)
    monkeypatch.setattr(cli.db, "connect", lambda: con)
    monkeypatch.setattr(cli.config, "root", lambda: tmp_path)
    cfg = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
    cfg["availability"]["provedores_assinados"] = ["Netflix"]
    monkeypatch.setattr(cli.config, "load", lambda: cfg)
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


def test_feedback_and_keyword_lookup(local_cli):
    runner, _, _ = local_cli
    packet = invoke_json(runner, ["feedback", "1", "bom"])
    assert packet["tmdb_id"] == 1 and packet["veredito"] == "bom"
    assert invoke_json(runner, ["keywords", "romantic"])["keywords"] == [
        {"nome": "romantic comedy", "filmes": 2}]
    assert invoke_json(runner, ["keywords", "inexistente"])["keywords"] == []


def test_invalid_feedback_does_not_write(local_cli):
    runner, root, _ = local_cli
    result = runner.invoke(cli.app, ["feedback", "1", "talvez", "--json"])
    assert result.exit_code != 0
    assert not (root / "overrides/feedback.csv").exists()


def mock_retrieval(monkeypatch):
    pool = cli.cand_mod.Pool()
    pool.add(1, "similar")
    pool.add(2, "watchlist")
    monkeypatch.setattr(cli.cand_mod, "generate", AsyncMock(return_value=pool))
    monkeypatch.setattr(cli.context_mod, "discover", AsyncMock(return_value=set()))
    monkeypatch.setattr(cli.enrich_mod, "fetch_movies", AsyncMock(return_value=SimpleNamespace(fetched=0)))


def test_now_empty_preserves_constraints_and_warns(local_cli, monkeypatch):
    runner, _, _ = local_cli
    mock_retrieval(monkeypatch)
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={}))
    packet = invoke_json(runner, ["now", "-g", "comedia", "-g", "romance", "--all-genres",
                                  "--max-runtime", "90", "--subscribed-only", "--exclude", "1"])
    assert packet["filmes"] == [] and packet["avisos"]
    assert "JustWatch" in packet["atribuicao"]
    ctx = packet["consulta"]
    assert ctx["genres"] == [35, 10749] and ctx["all_genres"]
    assert ctx["max_runtime"] == 90 and ctx["subscribed_only"] and ctx["exclude"] == [1]
    assert packet["diagnostico"]["context_matched"] == 1


@pytest.mark.parametrize("flags,expected", [([], [1, 2]), (["--streaming-only"], [2]),
                                           (["--subscribed-only"], [2]), (["--provider", "Netflix"], [2])])
def test_now_availability_is_metadata_unless_requested(local_cli, monkeypatch, flags, expected):
    runner, _, _ = local_cli
    mock_retrieval(monkeypatch)
    catalog = {2: {"flatrate": [{"provider_name": "Netflix"}]}}
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value=catalog))
    first = invoke_json(runner, ["now", "--n", "2", *flags])
    assert [f["tmdb_id"] for f in first["filmes"]] == expected
    assert first["diagnostico"]["retrieval_sources"] == {"similar": 1, "watchlist": 1}
    if not flags:
        monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={
            1: {"flatrate": [{"provider_name": "Other"}]}}))
        cli.config.load()["availability"]["provedores_assinados"] = ["Other"]
        second = invoke_json(runner, ["now", "--n", "2"])
        assert [(f["tmdb_id"], f["score"]) for f in first["filmes"]] == [
            (f["tmdb_id"], f["score"]) for f in second["filmes"]]


def test_explore_report_is_optional_and_order_is_shared(local_cli, monkeypatch):
    runner, root, _ = local_cli
    mock_retrieval(monkeypatch)
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={}))
    plain = invoke_json(runner, ["explore", "--n", "2"])
    assert not (root / "reports").exists()
    target = root / "reports" / "test.md"
    report = invoke_json(runner, ["explore", "--n", "2", "--markdown", str(target)])
    assert plain["filmes"] == report["filmes"]
    assert all(f["complemento_origem"] is False for f in plain["filmes"])
    assert set(plain["diagnostico"]["availability"]["origem"]) == {"cap", "dominante", "participacao", "complementos"}
    assert "Recomendações" in target.read_text(encoding="utf-8")
    assert "Disponível no streaming BR" not in target.read_text(encoding="utf-8")


def test_interaction_actions_and_contextual_feedback(local_cli, monkeypatch):
    runner, root, con = local_cli
    mock_retrieval(monkeypatch)
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={}))
    packet = invoke_json(runner, ["explore", "--n", "2"])
    iid = packet["interaction_id"]
    result = invoke_json(runner, ["feedback", "1", "not_now", "--interaction", iid])
    assert result["exclude"] == [1]
    assert not (root / "overrides/feedback.csv").exists()
    log = invoke_json(runner, ["interaction", iid])
    assert log["mode"] == "explore"
    assert [r["rank"] for r in log["opcoes"]] == [1, 2]
    assert log["opcoes"][0]["sources"] == ["similar"]
    assert {r["acao"] for r in log["acoes"]} == {"not_now"}
    # Contexto não vira exclusão permanente nem afinidade negativa.
    assert [f["tmdb_id"] for f in invoke_json(runner, ["now", "--n", "2"])["filmes"]] == [1, 2]
    bad = runner.invoke(cli.app, ["feedback", "999", "disliked", "--interaction", iid])
    assert bad.exit_code != 0 and not (root / "overrides/feedback.csv").exists()


def test_not_now_requires_context_and_never_writes_feedback(local_cli):
    runner, root, _ = local_cli
    assert runner.invoke(cli.app, ["feedback", "1", "not_now"]).exit_code != 0
    assert not (root / "overrides/feedback.csv").exists()


def test_profile_json_and_legacy_recommend(local_cli, monkeypatch):
    runner, root, _ = local_cli
    profile = invoke_json(runner, ["profile"])
    assert profile["resumo"]["filmes"] == 0 and profile["features"] == []
    mock_retrieval(monkeypatch)
    monkeypatch.setattr(cli.avail_mod, "fetch", AsyncMock(return_value={}))
    result = runner.invoke(cli.app, ["recommend", "--n", "2"])
    assert result.exit_code == 0, result.exception
    assert len(list((root / "reports").glob("*.md"))) == 1


@pytest.mark.parametrize("verdict", ["liked", "disliked", "not_interested", "already_seen"])
def test_persistent_feedback_excludes_from_future_queries(local_cli, monkeypatch, verdict):
    runner, _, _ = local_cli
    # Verifica o contrato da exclusão passado ao retrieval, não um pool simulado que ignora exclude.
    captured = []
    async def generate(con, tmdb, cfg, exclude, *args):
        captured.append(exclude)
        return cli.cand_mod.Pool()
    monkeypatch.setattr(cli.cand_mod, "generate", generate)
    monkeypatch.setattr(cli.context_mod, "discover", AsyncMock(return_value={1}))
    monkeypatch.setattr(cli.enrich_mod, "fetch_movies", AsyncMock(return_value=SimpleNamespace(fetched=0)))
    invoke_json(runner, ["feedback", "1", verdict])
    packet = invoke_json(runner, ["now"])
    assert 1 in captured[0] and packet["filmes"] == []


def test_now_progresses_beyond_old_200_candidate_cutoff(local_cli, monkeypatch):
    runner, _, con = local_cli
    con.execute("INSERT INTO film_meta(tmdb_id, title, original_title, year, vote_count, runtime) "
                "SELECT i, 'Film ' || i, 'Film ' || i, 2000, 100, 90 FROM range(3, 261) x(i)")
    mock_retrieval(monkeypatch)
    pool = cli.cand_mod.Pool()
    for tid in range(1, 261):
        pool.add(tid, "similar")
    monkeypatch.setattr(cli.cand_mod, "generate", AsyncMock(return_value=pool))
    fetch = AsyncMock(return_value={251: {"flatrate": [{"provider_name": "Netflix"}]}})
    monkeypatch.setattr(cli.avail_mod, "fetch", fetch)
    packet = invoke_json(runner, ["now", "--n", "1", "--subscribed-only"])
    assert [r["tmdb_id"] for r in packet["filmes"]] == [251]
    assert packet["diagnostico"]["availability"]["stop_reason"] == "filled"
    assert fetch.call_count == 6
