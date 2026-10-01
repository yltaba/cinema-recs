import json

import duckdb

from recs.db import SCHEMA
from recs.enrich import derive

PAYLOAD = {
    "id": 1, "title": "O Fantasma da Liberdade", "original_title": "Le Fantôme de la liberté",
    "release_date": "1974-09-11", "runtime": 104, "original_language": "fr", "vote_count": 344,
    "vote_average": 7.3, "popularity": 3.1, "imdb_id": "tt0071487", "overview": "...",
    "genres": [{"id": 35, "name": "Comédia"}],
    "production_countries": [{"iso_3166_1": "FR", "name": "France"}, {"iso_3166_1": "IT", "name": "Italy"}],
    "spoken_languages": [{"iso_639_1": "fr"}, {"iso_639_1": "es"}],
    "keywords": {"keywords": [{"id": 9, "name": "surrealism"}]},
    "credits": {"crew": [
        {"id": 100, "name": "Luis Buñuel", "job": "Director"},
        {"id": 100, "name": "Luis Buñuel", "job": "Screenplay"},
        {"id": 101, "name": "Jean-Claude Carrière", "job": "Screenplay"},
        {"id": 101, "name": "Jean-Claude Carrière", "job": "Writer"},
        {"id": 102, "name": "Edmond Richard", "job": "Director of Photography"},
        {"id": 103, "name": "Someone", "job": "Gaffer"},
    ]},
    "recommendations": {"results": [{"id": 2}]},
    "similar": {"results": [{"id": 2}, {"id": 3}]},
}


def test_derive_normalized_tables():
    con = duckdb.connect()
    con.execute(SCHEMA)
    con.execute("INSERT INTO tmdb_raw VALUES (1, now(), ?)", [json.dumps(PAYLOAD)])
    derive(con)

    assert con.execute("SELECT title, year, runtime, vote_count FROM film_meta").fetchone() == (
        "O Fantasma da Liberdade", 1974, 104, 344)
    people = set(con.execute("SELECT person_id, role FROM film_people").fetchall())
    # Screenplay + Writer da mesma pessoa vira um único "writer"; Gaffer fica fora.
    assert people == {(100, "director"), (100, "writer"), (101, "writer"), (102, "cinematographer")}
    assert sorted(con.execute("SELECT iso FROM film_countries").fetchall()) == [("FR",), ("IT",)]
    assert set(con.execute("SELECT iso, is_original FROM film_languages").fetchall()) == {("fr", True), ("es", False)}
    assert con.execute("SELECT count(*) FROM film_links").fetchone()[0] == 3
    assert con.execute("SELECT name FROM film_keywords").fetchall() == [("surrealism",)]
