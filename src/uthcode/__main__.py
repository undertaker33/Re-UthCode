"""Module entry point for ``python -m uthcode``."""

from .interfaces.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
