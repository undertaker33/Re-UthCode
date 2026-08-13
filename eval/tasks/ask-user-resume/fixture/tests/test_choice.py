from src.choice import display


def test_chosen_trim_semantics() -> None:
    assert display(" value ") == "value"
