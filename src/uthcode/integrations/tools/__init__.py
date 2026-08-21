"""Concrete tools owned by the Integration layer.

The package deliberately keeps its public surface narrow.  Application
composition will select concrete tools explicitly; callers use the Core Tool
contract rather than importing these adapters as a public API.
"""

from .history_read import (
    HISTORY_READ_SCHEMA_VERSION,
    HistoryReadBoundaryError,
    HistoryReadError,
    HistoryReadOutputLimitError,
    HistoryReadPage,
    HistoryReadPolicy,
    HistoryReadReferenceError,
    HistoryReadSessionError,
    HistoryReadTool,
    decode_history_ref,
    format_history_read_page,
)

__all__ = [
    "HISTORY_READ_SCHEMA_VERSION",
    "HistoryReadBoundaryError",
    "HistoryReadError",
    "HistoryReadOutputLimitError",
    "HistoryReadPage",
    "HistoryReadPolicy",
    "HistoryReadReferenceError",
    "HistoryReadSessionError",
    "HistoryReadTool",
    "decode_history_ref",
    "format_history_read_page",
]
