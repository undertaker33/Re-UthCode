class Record:
    def __init__(self, name: str, value: int) -> None:
        self.name = name
        self.value = value

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name}
