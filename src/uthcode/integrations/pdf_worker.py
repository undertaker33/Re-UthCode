"""Headless source entry point for the private PDF worker."""

from __future__ import annotations

import sys

from uthcode.integrations.tools.document_workers import PDF_WORKER_FLAG, pdf_worker_main


def main() -> None:
    if PDF_WORKER_FLAG not in sys.argv[1:]:
        raise SystemExit(f"{PDF_WORKER_FLAG} is required")
    pdf_worker_main()


if __name__ == "__main__":  # pragma: no cover - exercised by the parent process
    main()


__all__ = ["main"]
