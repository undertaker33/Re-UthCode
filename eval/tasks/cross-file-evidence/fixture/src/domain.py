def normalize(value: str, request_id: str | None = None) -> dict[str, str]:
    return {"value": value.strip(), "request_id": request_id or "generated"}
