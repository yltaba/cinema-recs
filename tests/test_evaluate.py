import duckdb
import pytest

from recs import evaluate
from recs.evaluate import SeedResult

CFG = {"score": {"popularity_alpha": 0.15, "sum_feature_types": ["keyword"]},
       "profile": {"feature_weights": {"director": 3.0}}}


def test_apply_overrides_copies_and_parses():
    out = evaluate.apply_overrides(CFG, ["score.popularity_alpha=0.3", "profile.feature_weights.director = 2",
                                         'score.sum_feature_types=["keyword","genre"]'])
    assert out["score"]["popularity_alpha"] == 0.3
    assert out["profile"]["feature_weights"]["director"] == 2
    assert out["score"]["sum_feature_types"] == ["keyword", "genre"]
    assert CFG["score"]["popularity_alpha"] == 0.15  # original intacto


def test_apply_overrides_rejects_unknown_key():
    with pytest.raises(KeyError):
        evaluate.apply_overrides(CFG, ["score.popularity_alfa=0.3"])


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE lb_films (lb_uri TEXT, watched BOOLEAN, rating DOUBLE)")
    c.execute("CREATE TABLE film_map (lb_uri TEXT, tmdb_id INTEGER)")
    c.execute("CREATE TABLE film_meta (tmdb_id INTEGER)")
    for i in range(40):
        c.execute("INSERT INTO lb_films VALUES (?, TRUE, ?)", [f"u{i}", 5.0 if i < 20 else 3.0])
        c.execute("INSERT INTO film_map VALUES (?, ?)", [f"u{i}", i])
        c.execute("INSERT INTO film_meta VALUES (?)", [i])
    return c


def test_holdout_is_deterministic_and_only_high_ratings(con):
    a = evaluate.holdout_ids(con, 4.5, 0.15, seed=1)
    assert a == evaluate.holdout_ids(con, 4.5, 0.15, seed=1)
    assert len(a) == 3 and all(i < 20 for i in a)
    assert a != evaluate.holdout_ids(con, 4.5, 0.15, seed=2)


def test_summarize_and_previous(con):
    rs = [SeedResult(1, 3, 0.5, 0.0, 1 / 3, 100), SeedResult(2, 3, 1.0, 1 / 3, 2 / 3, 300)]
    s = evaluate.summarize(rs)
    assert s["cand_recall"][0] == pytest.approx(0.75) and s["median_votes_top20"][0] == 200
    assert evaluate.previous(con, 0.15) is None
    evaluate.save(con, "baseline", 0.15, CFG, rs)
    label, means = evaluate.previous(con, 0.15)
    assert label.startswith("baseline") and means["hit50"] == pytest.approx(0.5)
    assert evaluate.previous(con, 0.3) is None
    evaluate.save(con, "outro", 0.15, CFG, rs[:1])
    assert evaluate.previous(con, 0.15)[0].startswith("outro")
    assert evaluate.previous(con, 0.15, "baseline")[0].startswith("baseline")
