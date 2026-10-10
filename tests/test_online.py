import json
from datetime import datetime

import duckdb

from recs import online
from recs.db import SCHEMA
from recs.interactions import ensure_schema


def make_con():
    con = duckdb.connect()
    con.execute(SCHEMA)
    ensure_schema(con)
    opts = [{"tmdb_id": 1, "rank": 1, "sources": ["filmografia:director", "filmografia:cinematographer"]},
            {"tmdb_id": 2, "rank": 2, "sources": ["movielens"]},
            {"tmdb_id": 3, "rank": 3, "sources": ["watchlist"]},
            {"tmdb_id": 4, "rank": 4, "sources": ["movielens"]},
            {"tmdb_id": 6, "rank": 5, "sources": ["discover:profile:country:JP"]}]
    con.execute("INSERT INTO interactions (interaction_id, created_at, mode, options) VALUES ('i1', ?, 'explore', ?)",
                [datetime(2026, 10, 1, 20), json.dumps(opts)])
    # (lb_uri, tmdb_id, nota, data): 3 foi visto antes da indicação; 5 e 7 não foram indicados (base).
    for uri, tid, rating, logged in [("u1", 1, 4.5, "2026-10-05"), ("u3", 3, 5.0, "2026-09-01"),
                                     ("u5", 5, 3.0, "2026-10-03"), ("u7", 7, 2.0, "2020-01-01")]:
        con.execute("INSERT INTO lb_films VALUES (?, 'x', 2000, ?, true, false, false, NULL, ?)", [uri, rating, logged])
        con.execute("INSERT INTO film_map VALUES (?, ?, 'exact', 1)", [uri, tid])
    return con


def test_online_eval_compares_recommended_with_period_baseline():
    con = make_con()
    ratings = {2: {"nota": 3.5, "like": False, "data": "2026-10-02", "titulo": "Dois"}}
    feedback = {4: ("already_seen", "2026-10-04"), 6: ("not_interested", "2026-10-04")}
    out = online.evaluate(con, ratings, feedback)
    assert out["periodo_desde"] == "2026-10-01" and out["indicados"] == 5
    assert [f["tmdb_id"] for f in out["filmes"]] == [2, 4, 1]  # 3 foi visto antes; 6 não é visto
    assert out["com_nota"] == 2 and out["media_indicados"] == 4.0
    assert out["media_sem_indicacao_periodo"] == 3.0 and out["n_sem_indicacao_periodo"] == 1
    assert abs(out["media_geral_letterboxd"] - 3.625) < 0.01  # (4.5 + 5 + 3 + 2) / 4
    fontes = {r["fonte"]: r for r in out["por_fonte"]}
    assert fontes["filmografia"] == {"fonte": "filmografia", "indicados": 1, "assistidos": 1, "com_nota": 1, "media": 4.5}
    assert fontes["movielens"]["assistidos"] == 2 and fontes["movielens"]["media"] == 3.5
    assert fontes["watchlist"]["assistidos"] == 0 and fontes["discover"]["indicados"] == 1
    assert any("amostra pequena" in a for a in out["avisos"])


def test_online_eval_without_interactions():
    con = duckdb.connect()
    con.execute(SCHEMA)
    ensure_schema(con)
    assert online.evaluate(con, {}, {})["indicados"] == 0
