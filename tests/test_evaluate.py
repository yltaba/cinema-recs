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


def test_ndcg_mrr_and_diversity_known_ranking():
    import math
    rows = [{"tmdb_id": i, "director_ids": [d]} for i, d in [(1, 1), (2, 1), (3, 2)]]
    metrics = evaluate.ranking_metrics(rows, {2, 3})
    assert metrics["mrr50"] == 0.5
    assert metrics["ndcg20"] == pytest.approx((1 / math.log2(3) + 0.5) / (1 + 1 / math.log2(3)))
    assert metrics["director_diversity20"] == pytest.approx(2 / 3)
    assert evaluate.ranking_metrics([], {2})["director_diversity20"] is None
    assert evaluate.ranking_metrics(rows, set())["ndcg20"] == 0


def test_max_country_share_measures_origin_concentration():
    rows = [{"tmdb_id": i, "director_ids": [], "countries": c} for i, c in enumerate(["JP", "JP/FR", "US", None])]
    assert evaluate.ranking_metrics(rows, set())["max_country_share20"] == 0.5
    assert evaluate.ranking_metrics([], set())["max_country_share20"] is None


def test_old_eval_schema_preserved_and_extended(con):
    con.execute("CREATE TABLE eval_runs(run_at TIMESTAMP, label TEXT, holdout DOUBLE, seed INTEGER, n_holdout INTEGER, "
                "cand_recall DOUBLE, hit20 DOUBLE, hit50 DOUBLE, median_votes_top20 DOUBLE, config JSON)")
    con.execute("INSERT INTO eval_runs VALUES ('2020-01-01', 'old', 0.15, 1, 3, 0.5, 0.1, 0.2, 100, '{}')")
    assert evaluate.previous(con, 0.15)[1]["ndcg20"] is None
    evaluate.save(con, "new", 0.15, CFG, [SeedResult(1, 3, 1, 1, 1, 100, ndcg20=1, mrr50=1)])
    assert con.execute("SELECT count(*) FROM eval_runs").fetchone()[0] == 2
    assert evaluate.previous(con, 0.15)[1]["ndcg20"] == 1


def test_empty_holdout_and_invalid_fraction(con):
    assert evaluate.holdout_ids(con, 6, 0.15, 1) == []
    with pytest.raises(ValueError):
        evaluate.holdout_ids(con, 4.5, 1.2, 1)
