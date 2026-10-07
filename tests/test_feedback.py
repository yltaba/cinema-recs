from recs import feedback


def test_legacy_normalization_does_not_rewrite(tmp_path):
    path = tmp_path / "feedback.csv"
    original = "tmdb_id,veredito,data\n1,bom,2026-01-01\n2,nao,2026-01-01\n3,ja_vi,2026-01-01\n"
    path.write_text(original, encoding="utf-8")
    assert feedback.load(path) == {1: "liked", 2: "not_interested", 3: "already_seen"}
    assert path.read_text(encoding="utf-8") == original
    feedback.append(path, 1, "disliked")
    assert feedback.load(path)[1] == "disliked"
    assert feedback.excluded(feedback.load(path)) == {1, 2, 3}
