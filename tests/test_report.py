from types import SimpleNamespace

from recs import report
from recs.availability import Availability


def _row(**kw):
    return {"tmdb_id": 1, "title": "Filme", "original_title": "Film", "year": 2000, "directors": "Diretora",
            "runtime": 90, "genres": ["Comedy"], "countries": "FR", "sources": ["watchlist"], "base": 1.0,
            "context_score": 0.8, "reasons": [("diretor", "Diretora", 0.5)], "prefer_hits": [],
            "availability": Availability(streaming=["Netflix", "Looke"], subscribed=["Netflix"], known=True), **kw}


def test_explore_report_separates_complements(tmp_path):
    rows = [_row(), _row(tmdb_id=2, title="Outro", original_title="Outro", origin_complement=True,
                         availability=Availability(known=False))]
    diag = {"retrieved": 10, "eligible": 9, "context_matched": 5}
    path = report.write_explore(tmp_path / "r.md", rows, diag, {
        "contexto": "gênero: comedy", "mode": "explore", "interaction_id": "abc", "warnings": ["aviso"]})
    text = path.read_text(encoding="utf-8")
    assert "### 1. Filme (Film) 📌 — 2000" in text and "**Netflix**, Looke" in text
    assert text.index("## De outros lugares") < text.index("### 2. Outro")
    assert "sem dado de disponibilidade" in text and "- aviso" in text
    assert text.rstrip().endswith(report.ATTRIBUTION)


def test_match_review_only_exists_with_pending_items(tmp_path):
    path = tmp_path / "revisao-match.md"
    film = {"name": "Split", "year": 2016}
    assert report.write_match_review(path, [(film, SimpleNamespace(tmdb_id=5, method="exact", confidence=0.85))],
                                     [], {5: ("Split", "2016")})
    assert "[Split (2016)](https://www.themoviedb.org/movie/5)" in path.read_text(encoding="utf-8")
    assert not report.write_match_review(path, [], [], {})
    assert not path.exists()
