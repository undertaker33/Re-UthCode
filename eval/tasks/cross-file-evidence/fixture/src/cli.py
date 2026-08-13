from .application import handle


def run(value: str, request_id: str | None = None) -> dict[str, str]:
    return handle({"value": value})
