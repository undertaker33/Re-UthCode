from .implementation import format_result


def render(value: str, *, compact: bool = False) -> str:
    return format_result(value, compact=compact)
