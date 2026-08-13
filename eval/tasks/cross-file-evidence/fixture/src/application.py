from .domain import normalize


def handle(request: dict[str, str | None]) -> dict[str, str]:
    return normalize(request["value"] or "")
