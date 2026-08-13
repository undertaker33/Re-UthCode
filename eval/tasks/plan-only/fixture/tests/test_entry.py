from src.entry import answer


def test_answer() -> None:
    assert answer(" value ") == "value"
