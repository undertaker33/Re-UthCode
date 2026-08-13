from .model import Record


def encode(record: Record) -> dict[str, object]:
    return record.to_dict()


def decode(payload: dict[str, object]) -> Record:
    return Record(str(payload["name"]), 0)
