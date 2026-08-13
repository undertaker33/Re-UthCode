from src.slug import slugify


def test_slugify_collapses_spaces_and_punctuation() -> None:
    assert slugify(" Hello,   World! ") == "hello-world"
