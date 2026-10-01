import asyncio

import pytest

from recs.match import Match, choose_fuzzy, choose_strict, load_overrides, normalize, resolve

CFG = {
    "tmdb": {"search_ttl_days": 90},
    "match": {"search_language": "en-US", "accept_threshold": 0.85, "min_margin": 0.03},
}


def movie(id, title, year, original=None, votes=100):
    return {"id": id, "title": title, "original_title": original or title,
            "release_date": f"{year}-06-01" if year else "", "vote_count": votes}


@pytest.mark.parametrize("a,b", [
    ("The Godfather", "Godfather"),
    ("The Phantom of Liberty", "Phantom of Liberty"),
    ("O Auto da Compadecida", "Auto da Compadecida"),
    ("Le Samouraï", "Samourai"),
    ("L'Avventura", "Avventura"),
    ("La Dolce Vita", "Dolce Vita"),
    ("Amélie", "Amelie"),
    ("Mr. & Mrs. Smith", "mr and mrs smith"),
    ("Godzilla: King of the Monsters", "Godzilla King of the Monsters"),
])
def test_normalize_equivalences(a, b):
    assert normalize(a) == normalize(b)


def test_normalize_keeps_single_word_article():
    assert normalize("A") == "a"
    assert normalize("Them!") == "them"


def test_exact_title_with_article_difference():
    results = [movie(1, "Phantom of Liberty", 1974, "Le Fantôme de la liberté"), movie(2, "Liberty", 1974)]
    m = choose_strict("The Phantom of Liberty", 1974, results)
    assert m.tmdb_id == 1 and m.method == "exact"


def test_original_title_matches():
    # Letterboxd às vezes usa o título original; o TMDB em en-US devolve o título traduzido.
    results = [movie(10, "The Exterminating Angel", 1962, "El ángel exterminador"), movie(11, "Angel", 1962)]
    assert choose_strict("El ángel exterminador", 1962, results).tmdb_id == 10


def test_translated_title_single_result():
    results = [movie(20, "Relatos Selvagens", 2014, "Relatos salvajes")]
    m = choose_strict("Wild Tales", 2014, results)
    assert m.tmdb_id == 20 and m.method == "single"


def test_single_result_wrong_year_rejected():
    assert choose_strict("Wild Tales", 2014, [movie(20, "Relatos Selvagens", 1990)]) is None


@pytest.mark.parametrize("year,expected", [(1977, 1), (2018, 2)])
def test_remake_same_name_picked_by_year(year, expected):
    results = [movie(1, "Suspiria", 1977, votes=2000), movie(2, "Suspiria", 2018, votes=3000)]
    assert choose_strict("Suspiria", year, results).tmdb_id == expected


def test_remake_off_by_one_year_prefers_closest():
    results = [movie(1, "Funny Games", 1997), movie(2, "Funny Games", 2007, votes=5000)]
    assert choose_strict("Funny Games", 1998, results).tmdb_id == 1


def test_same_title_same_year_tie_is_low_confidence():
    results = [movie(1, "Crash", 2004, votes=400), movie(2, "Crash", 2004, votes=500)]
    m = choose_strict("Crash", 2004, results)
    assert m.tmdb_id == 2 and m.confidence < 0.9


def test_same_title_same_year_clear_winner_is_confident():
    results = [movie(1, "Taxi Driver", 1976, votes=3), movie(2, "Taxi Driver", 1976, votes=12000)]
    m = choose_strict("Taxi Driver", 1976, results)
    assert m.tmdb_id == 2 and m.confidence >= 0.9


def test_fuzzy_needs_margin():
    results = [movie(1, "Blue Velvet Nights", 1986), movie(2, "Blue Velvet Night", 1986)]
    m = choose_fuzzy("Blue Velvet", 1986, results, 0.6, 0.03)
    assert m.tmdb_id is None and m.method == "unmatched" and len(m.candidates) == 2


def test_fuzzy_accepts_close_title():
    results = [movie(1, "Godfather Part II", 1974), movie(2, "Godfather", 1972)]
    m = choose_fuzzy("The Godfather: Part II", 1974, results, 0.85, 0.03)
    assert m.tmdb_id == 1


class FakeTMDB:
    def __init__(self, table):
        self.table, self.seen = table, []

    async def get(self, path, ttl_days, **params):
        key = tuple(sorted((k, v) for k, v in params.items() if k in ("year", "primary_release_year") and v))
        self.seen.append(key)
        return {"results": self.table.get(key, [])}


def test_resolve_widens_year_when_first_search_fails():
    # Letterboxd diz 2015, TMDB data o lançamento em 2014.
    fake = FakeTMDB({(("primary_release_year", 2014),): [movie(5, "Mustang", 2014)]})
    m = asyncio.run(resolve(fake, "Mustang", 2015, CFG))
    assert m.tmdb_id == 5 and m.method == "exact_widened"
    assert len(fake.seen) == 4


def test_resolve_strict_hit_uses_one_call():
    fake = FakeTMDB({(("year", 1974),): [movie(1, "The Phantom of Liberty", 1974)]})
    m = asyncio.run(resolve(fake, "The Phantom of Liberty", 1974, CFG))
    assert m == Match(1, "exact", m.confidence) and len(fake.seen) == 1


def test_overrides(tmp_path):
    p = tmp_path / "matches.csv"
    p.write_text("lb_uri,name,year,tmdb_id,note\nhttps://boxd.it/x,,,123,\n,Some Series,2010,,tv\n", encoding="utf-8")
    o = load_overrides(p)
    assert o["https://boxd.it/x"] == 123
    assert o[("Some Series", 2010)] is None
