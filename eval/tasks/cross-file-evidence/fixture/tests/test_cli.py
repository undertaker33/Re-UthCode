from src.cli import run


def test_request_id_survives_the_application_boundary() -> None:
    assert run(" value ", "req-7") == {"value": "value", "request_id": "req-7"}
    assert run(" value ") == {"value": "value", "request_id": "generated"}
