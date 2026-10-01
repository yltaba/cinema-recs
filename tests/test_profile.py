import json
import math

import duckdb
import pytest

from recs import profile
from recs.db import SCHEMA
from recs.enrich import derive

CFG = {"profile": {"unrated_weight": 0.1, "liked_bonus": 0.2, "feedback_good_weight": 0.3, "shrinkage_k": 2.0}}


def payload(i, director, keywords, year=2000):
    return {
        "id": i, "title": f"F{i}", "original_title": f"F{i}", "release_date": f"{year}-01-01", "runtime": 100,
        "original_language": "fr", "vote_count": 100, "genres": [], "production_countries": [],
        "spoken_languages": [], "keywords": {"keywords": [{"id": k, "name": f"kw{k}"} for k in keywords]},
        "credits": {"crew": [{"id": director, "name": f"D{director}", "job": "Director"}]},
    }


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(SCHEMA)
    # id, diretor, keywords, nota, like, visto
    films = [
        (1, 10, [1, 9], 5.0, False, True),
        (2, 10, [1, 9], 4.0, False, True),
        (3, 20, [2, 9], 2.0, False, True),
        (4, 30, [9], None, True, True),     # visto sem nota, com like
        (5, 40, [9], None, False, False),   # só watchlist: fora do perfil
    ]
    for i, d, kws, rating, liked, watched in films:
        c.execute("INSERT INTO tmdb_raw VALUES (?, now(), ?)", [i, json.dumps(payload(i, d, kws))])
        c.execute("INSERT INTO lb_films VALUES (?, ?, 2000, ?, ?, ?, ?, NULL, NULL)",
                  [f"u{i}", f"F{i}", rating, watched, not watched, liked])
        c.execute("INSERT INTO film_map VALUES (?, ?, 'exact', 1.0)", [f"u{i}", i])
    derive(c)
    return c


def aff(con, ft, fid):
    return con.execute("SELECT affinity, n FROM profile_features WHERE feature_type = ? AND feature_id = ?",
                       [ft, str(fid)]).fetchone()


def test_film_weights(con):
    profile.build(con, CFG)
    w = dict(con.execute("SELECT tmdb_id, w FROM profile_films").fetchall())
    # média das notas = (5 + 4 + 2) / 3
    mu = 11 / 3
    assert w[1] == pytest.approx(5 - mu)
    assert w[3] == pytest.approx(2 - mu)
    assert w[4] == pytest.approx(0.1 + 0.2)
    assert 5 not in w


def test_shrinkage(con):
    profile.build(con, CFG)
    mu = 11 / 3
    a, n = aff(con, "director", 10)
    assert n == 2 and a == pytest.approx(((5 - mu) + (4 - mu)) / (2 + 2))
    a1, _ = aff(con, "director", 20)
    assert a1 == pytest.approx((2 - mu) / 3)


def test_keyword_idf(con):
    profile.build(con, CFG)
    assert aff(con, "keyword", 9)[0] == pytest.approx(0.0)  # presente em todos os filmes do perfil
    mu = 11 / 3
    a, n = aff(con, "keyword", 1)
    assert n == 2 and a == pytest.approx(((5 - mu) + (4 - mu)) / 4 * math.log(4 / 2) / math.log(4))


def test_exclude_and_feedback(con):
    profile.build(con, CFG, exclude={1}, feedback={5: "bom", 3: "nao"})
    w = dict(con.execute("SELECT tmdb_id, w FROM profile_films").fetchall())
    assert 1 not in w
    assert w[5] == pytest.approx(0.3)
    assert w[2] == pytest.approx(4 - 3.0)  # média recalculada sem o filme excluído
