import duckdb
import pytest

from recs import context

CFG = {
    "availability": {"region": "BR"},
    "now": {"discover_min_votes": 50, "discover_quality_votes": 300, "discover_pages": 1},
}


def test_parse_genres_pt_and_en():
    assert context.parse_genres(["comédia", "Romance"]) == [35, 10749]
    assert context.parse_genres(["terror,horror"]) == [27]
    assert context.parse_genres(["ficção científica"]) == [878]
    with pytest.raises(ValueError):
        context.parse_genres(["engraçado"])


@pytest.mark.parametrize("s,expected", [
    ("1990s", (1990, 1999)), ("90s", (1990, 1999)), ("10s", (2010, 2019)), ("1980-2000", (1980, 2000)),
    ("2010-", (2010, None)), ("-1979", (None, 1979)), ("1975", (1975, 1975)), (None, (None, None)),
])
def test_parse_years(s, expected):
    assert context.parse_years(s) == expected


def test_parse_years_invalid():
    with pytest.raises(ValueError):
        context.parse_years("anos 80")


def test_discover_params():
    ctx = context.build(genre=["comedia", "romance"], max_runtime=120, years="1990s", language=["ja"],
                        subscribed_only=True)
    quality, popular = context.discover_params(ctx, CFG, [8, 119])
    assert quality["with_genres"] == "35|10749" and quality["with_runtime.lte"] == 120
    assert quality["primary_release_date.gte"] == "1990-01-01" and quality["primary_release_date.lte"] == "1999-12-31"
    assert quality["with_original_language"] == "ja" and quality["with_watch_providers"] == "8|119"
    assert quality["sort_by"] == "vote_average.desc" and quality["vote_count.gte"] == 300
    assert popular["sort_by"] == "popularity.desc" and popular["vote_count.gte"] == 50


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE film_meta (tmdb_id INT, runtime INT, original_language TEXT, year INT)")
    c.execute("CREATE TABLE film_genres (tmdb_id INT, genre_id INT, name TEXT)")
    c.execute("CREATE TABLE film_countries (tmdb_id INT, iso TEXT, name TEXT)")
    c.execute("CREATE TABLE film_keywords (tmdb_id INT, keyword_id INT, name TEXT)")
    c.execute("CREATE TABLE scores (tmdb_id INT, score DOUBLE, eligible BOOLEAN)")
    films = [  # id, runtime, idioma, ano, gêneros, keywords
        (1, 100, "en", 1999, [35], [(10, "lighthearted")]),
        (2, 150, "en", 2005, [35], []),                          # longo demais
        (3, 95, "fr", 1990, [18], []),                           # não é comédia
        (4, 90, "en", 2001, [35, 10749], [(20, "extreme gore")]),  # evitado
        (5, 0, "en", 2001, [35], []),                            # duração desconhecida com --max-runtime
        (6, 110, "ja", 2010, [35], [(10, "lighthearted"), (30, "feelgood")]),
    ]
    for tid, rt, lang, year, genres, kws in films:
        c.execute("INSERT INTO film_meta VALUES (?, ?, ?, ?)", [tid, rt, lang, year])
        c.execute("INSERT INTO scores VALUES (?, 1.0, TRUE)", [tid])
        for g in genres:
            c.execute("INSERT INTO film_genres VALUES (?, ?, '')", [tid, g])
        for kid, name in kws:
            c.execute("INSERT INTO film_keywords VALUES (?, ?, ?)", [tid, kid, name])
    return c


def test_keyword_ids_exact_vs_whole_word(con):
    assert context.keyword_ids(con, ["gore"], whole_word=True) == {20: "extreme gore"}
    assert context.keyword_ids(con, ["gore"], whole_word=False) == {}
    assert context.keyword_ids(con, ["Feelgood", "lighthearted"], whole_word=False) == {10: "lighthearted",
                                                                                         30: "feelgood"}
    assert context.keyword_ids(con, ["light"], whole_word=True) == {}  # palavra inteira, não trecho


def test_matching_filters_and_hits(con):
    ctx = context.build(genre=["comedy"], max_runtime=120, avoid=["gore"], prefer=["lighthearted", "feelgood"])
    hits = context.matching(con, ctx, sorted(context.keyword_ids(con, ctx.avoid_keywords, True)),
                            sorted(context.keyword_ids(con, ctx.prefer_keywords, False)))
    assert hits == {1: ["lighthearted"], 6: ["feelgood", "lighthearted"]}


def test_matching_language_years_exclude(con):
    ctx = context.build(language=["EN"], years="2000s", exclude=["5"])
    assert set(context.matching(con, ctx, [], [])) == {2, 4}


def test_rerank_bonus_only_for_positive_scores():
    rows = [{"tmdb_id": 1, "score": 1.0}, {"tmdb_id": 2, "score": 0.8}, {"tmdb_id": 3, "score": -0.5}]
    out = context.rerank(rows, {2: ["a", "b"], 3: ["a"]}, 0.25)
    assert [r["tmdb_id"] for r in out] == [2, 1, 3]
    assert out[0]["context_score"] == pytest.approx(1.2) and out[2]["context_score"] == -0.5


def test_warnings():
    ctx = context.build(prefer=["feelgod"], avoid=["xyz"])
    w = context.warnings(ctx, {}, {}, found=3, wanted=8)
    assert len(w) == 3 and "feelgod" in w[0]
