import math

import duckdb
import pytest

from recs import score
from recs.availability import classify, is_subscribed

CFG = {
    "profile": {"feature_weights": {"director": 3.0, "keyword": 1.0, "country": 1.0}},
    "candidates": {"watchlist_boost": 1.3},
    "score": {"popularity_alpha": 0.15, "min_vote_count": 20, "min_runtime": 60, "include_shorts": False,
              "include_documentaries": True, "sum_feature_types": ["keyword"]},
}


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE film_meta (tmdb_id INT, vote_count INT, runtime INT)")
    c.execute("CREATE TABLE film_genres (tmdb_id INT, genre_id INT, name TEXT)")
    c.execute("CREATE TABLE film_features (tmdb_id INT, feature_type TEXT, feature_id TEXT, label TEXT)")
    c.execute("CREATE TABLE profile_features (feature_type TEXT, feature_id TEXT, label TEXT, affinity DOUBLE, n INT)")
    c.execute("CREATE TABLE candidates (tmdb_id INT, sources TEXT[], exempt BOOLEAN)")
    c.executemany("INSERT INTO profile_features VALUES (?, ?, ?, ?, ?)", [
        ("director", "1", "Bong", 0.6, 2), ("keyword", "k1", "nihilism", 0.5, 4),
        ("keyword", "k2", "insomnia", 0.4, 2), ("country", "JP", "Japan", 0.6, 5),
    ])
    return c


def add(c, tid, feats, votes=100, runtime=100, sources=("recommendations",), exempt=False, genres=()):
    c.execute("INSERT INTO film_meta VALUES (?, ?, ?)", [tid, votes, runtime])
    c.execute("INSERT INTO candidates VALUES (?, ?, ?)", [tid, list(sources), exempt])
    c.executemany("INSERT INTO film_features VALUES (?, ?, ?, '')", [(tid, t, f) for t, f in feats])
    for g in genres:
        c.execute("INSERT INTO film_genres VALUES (?, ?, '')", [tid, g])


def row(c, tid):
    return c.execute("SELECT base, pop_penalty, boost, score, eligible FROM scores WHERE tmdb_id = ?", [tid]).fetchone()


def test_base_penalty_and_boost(con):
    add(con, 1, [("director", "1"), ("keyword", "k1"), ("keyword", "k2"), ("keyword", "zz")], votes=100,
        sources=("watchlist",))
    score.compute(con, CFG)
    base, pen, boost, s, ok = row(con, 1)
    assert base == pytest.approx(3.0 * 0.6 + 0.5 + 0.4)  # keywords somam
    assert pen == pytest.approx(1 / (1 + 0.15 * math.log1p(100)))
    assert boost == 1.3 and s == pytest.approx(base * pen * 1.3) and ok


def test_people_are_averaged_within_film(con):
    # Antologia: 1 diretor conhecido entre 4 → contribuição dividida por 4.
    add(con, 2, [("director", "1"), ("director", "x"), ("director", "y"), ("director", "z")])
    score.compute(con, CFG)
    assert row(con, 2)[0] == pytest.approx(3.0 * 0.6 / 4)


def test_filters(con):
    add(con, 3, [("country", "JP")], votes=5)
    add(con, 4, [("country", "JP")], runtime=20)
    add(con, 5, [("country", "JP")], votes=5, runtime=20, sources=("watchlist",), exempt=True)
    add(con, 6, [("country", "JP")], runtime=0)  # duração desconhecida não elimina
    score.compute(con, CFG)
    assert [row(con, i)[4] for i in (3, 4, 5, 6)] == [False, False, True, True]


def test_documentaries_flag(con):
    add(con, 7, [("country", "JP")], genres=(99,))
    score.compute(con, {**CFG, "score": {**CFG["score"], "include_documentaries": False}})
    assert row(con, 7)[4] is False


def test_reasons_order(con):
    add(con, 8, [("director", "1"), ("keyword", "k2"), ("country", "JP")])
    score.compute(con, CFG)
    assert [label for _, label, _ in score.reasons(con, 8)] == ["Bong", "Japan", "insomnia"]


def test_diversify():
    rows = [{"tmdb_id": i, "director_ids": [d]} for i, d in enumerate([1, 1, 1, 2, 2, 3])]
    out = score.diversify(rows, 4, 2)
    assert [r["tmdb_id"] for r in out] == [0, 1, 3, 4]


@pytest.mark.parametrize("name,expected", [
    ("Netflix", True), ("Netflix Standard with Ads", True), ("Amazon Prime Video with Ads", True),
    ("HBO Max", True), ("HBO Max Amazon Channel", False), ("MUBI Amazon Channel", False),
    ("Apple TV", True), ("MGM+ Apple TV Channel", False), ("Looke", False),
])
def test_is_subscribed(name, expected):
    subs = ["Netflix", "Amazon Prime Video", "HBO Max", "Disney Plus", "Apple TV", "MUBI"]
    assert is_subscribed(name, subs) is expected


def test_classify():
    a = classify({"flatrate": [{"provider_name": "Netflix"}, {"provider_name": "Netflix Standard with Ads"},
                               {"provider_name": "Looke"}], "rent": [{"provider_name": "Apple TV"}]},
                 ["Netflix"])
    assert a.available and a.streaming == ["Netflix", "Looke"] and a.subscribed == ["Netflix"] and a.rent_buy
    b = classify({"buy": [{"provider_name": "Google Play Movies"}]}, ["Netflix"])
    assert not b.available and b.rent_buy
    assert not classify(None, []).available
