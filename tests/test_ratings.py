import pytest

from recs import ratings


def test_append_load_last_row_wins_and_multiline_review(tmp_path):
    path = tmp_path / "overrides" / "avaliacoes.csv"
    ratings.append(path, 7, "After Hours", 4.0, True, 'Noite "absurda",\nengraçada', "iid-1")
    ratings.append(path, 7, "After Hours", 4.5, True, "melhor na segunda vez")
    ratings.append(path, 8, "Outro", None, False)
    loaded = ratings.load(path)
    assert loaded[7]["nota"] == 4.5 and loaded[7]["critica"] == "melhor na segunda vez"
    assert loaded[8]["nota"] is None and not loaded[8]["like"]
    assert ratings.excluded(loaded) == {7, 8}
    ratings.append(path, 9, "X", 3.0, False, 'a,b\n"c"')
    assert ratings.load(path)[9]["critica"] == 'a,b\n"c"'


@pytest.mark.parametrize("nota", [0, 0.3, 5.5, -1])
def test_invalid_rating_is_rejected_without_writing(tmp_path, nota):
    path = tmp_path / "avaliacoes.csv"
    with pytest.raises(ValueError):
        ratings.append(path, 1, "F", nota, False)
    assert not path.exists()


def test_load_missing_file(tmp_path):
    assert ratings.load(tmp_path / "nao-existe.csv") == {}
