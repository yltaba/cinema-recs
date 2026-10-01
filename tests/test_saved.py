from recs import saved


def test_add_and_load_dedupes(tmp_path):
    p = tmp_path / "salvos.csv"
    assert saved.add(p, [(1, "A"), (2, "B")], "policial") == [1, 2]
    assert saved.add(p, [(2, "B"), (3, "C")]) == [3]
    items = saved.load(p)
    assert list(items) == [1, 2, 3] and items[1]["contexto"] == "policial" and items[3]["titulo"] == "C"
    assert saved.load(tmp_path / "nada.csv") == {}
