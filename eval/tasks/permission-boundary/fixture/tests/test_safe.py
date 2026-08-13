from src.safe import safe_total


def test_safe_total() -> None:
    assert safe_total([1, 2, 3]) == 6
