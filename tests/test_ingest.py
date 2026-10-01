from recs.ingest import build


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_build_joins_diary_and_reviews_by_name_year(tmp_path):
    write(tmp_path / "watched.csv", "Date,Name,Year,Letterboxd URI\n2020-01-01,Wild Tales,2014,https://boxd.it/F1\n")
    write(tmp_path / "ratings.csv", "Date,Name,Year,Letterboxd URI,Rating\n2020-01-02,Wild Tales,2014,https://boxd.it/F1,4.5\n")
    write(tmp_path / "watchlist.csv", "Date,Name,Year,Letterboxd URI\n2020-01-03,Totoro,1988,https://boxd.it/F2\n")
    write(tmp_path / "likes" / "films.csv", "Date,Name,Year,Letterboxd URI\n2020-01-04,Wild Tales,2014,https://boxd.it/F1\n")
    # URIs de diário/resenha são da entrada, não do filme.
    write(tmp_path / "diary.csv",
          "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
          "2020-03-18,Wild Tales,2014,https://boxd.it/D1,5,,,2015-01-14\n"
          "2020-03-18,Ghost,1999,https://boxd.it/D2,3,,,2015-01-14\n")
    write(tmp_path / "reviews.csv",
          "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Review,Tags,Watched Date\n"
          "2020-05-22,Wild Tales,2014,https://boxd.it/R1,5,,Ótimo.,,2020-05-22\n")

    films, stats = build(tmp_path)
    by = {f["lb_uri"]: f for f in films}
    assert set(by) == {"https://boxd.it/F1", "https://boxd.it/F2"}
    wt = by["https://boxd.it/F1"]
    assert wt["rating"] == 4.5 and wt["watched"] and wt["liked"] and wt["review_text"] == "Ótimo."
    assert wt["last_logged"] == "2020-01-01"  # data do watched é posterior à do diário
    assert by["https://boxd.it/F2"]["in_watchlist"] and not by["https://boxd.it/F2"]["watched"]
    assert stats.orphans == ["Ghost (1999)"]
