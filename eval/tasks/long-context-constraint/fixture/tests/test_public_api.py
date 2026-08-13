import inspect

from src.public_api import render


def test_signature_is_stable() -> None:
    assert str(inspect.signature(render)) == "(value: str, *, compact: bool = False) -> str"


def test_format_result() -> None:
    assert render(" value ") == "value."
    assert render(" value ", compact=True) == "value"
