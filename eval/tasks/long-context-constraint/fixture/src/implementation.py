def format_result(value: str, *, compact: bool = False) -> str:
    return value.strip() if compact else value.strip() + "!"
