"""Display-safe summaries for shell commands crossing permission boundaries."""

from __future__ import annotations

import re


_BASH_GUARD_FACT_MARKER = "__uthcode_guard_fact__"
_SENSITIVE_ASSIGNMENT_NAME = (
    r"(?:[A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|passwd|authorization|credential)"
    r"[A-Za-z0-9_-]*|(?:key|auth)|[A-Za-z0-9]+(?:[_-](?:key|auth))"
    r"(?:[_-][A-Za-z0-9]+)*|(?:key|auth)(?:[_-][A-Za-z0-9]+)+)"
)
_COMMAND_URL_USERINFO = re.compile(
    r"(?i)(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/\s@]+)@"
)
_COMMAND_AUTH_HEADER = re.compile(
    r"(?i)(?P<prefix>\b(?:Proxy-)?Authorization\s*[:=]\s*"
    r"(?:(?:Bearer|Basic|Digest|NTLM)\s+)?)"
    r"(?P<value>[^\s,;\"']+)"
)
_COMMAND_QUERY_SECRET = re.compile(
    r"(?i)(?P<prefix>[?&](?:access[_-]?token|api[_-]?key|auth(?:entication)?|"
    r"client[_-]?secret|password|passwd|private[_-]?key|pwd|secret|token)=)"
    r"(?P<value>[^&#\s\"';]+)"
)
_COMMAND_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?!(?:Proxy-)?Authorization\s*[:=]\s*"
    r"(?:Bearer|Basic|Digest|NTLM)\s+)"
    rf"{_SENSITIVE_ASSIGNMENT_NAME}\s*[:=]\s*)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s;&|\"']+)"
)
_COMMAND_AUTH_OPTION = re.compile(
    r"(?ix)(?P<prefix>(?:--(?:user|password|proxy-user|proxy-password|"
    r"http-user|http-password|ftp-user|ftp-password|oauth2-bearer)\b|"
    r"-(?:u|U)))"
    r"(?P<separator>\s+|=|(?=[^\s]))"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s;&|]+)"
)
_BEARER_SECRET = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])Bearer\s+[^\s;&|\"']+"
)
_BARE_API_KEY = re.compile(r"(?i)\bsk-[A-Za-z0-9][A-Za-z0-9_.:/-]*")


def _redact_quoted_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return f"{value[0]}<redacted>{value[0]}"
    return "<redacted>"


def safe_bash_command_summary(command: str) -> str:
    """Return a bounded shell summary with conservative credential redaction.

    Command names, separators, flags, and non-sensitive arguments remain
    visible for risk review. Authentication values are removed by shape
    before generic token cleanup so URL userinfo, curl/wget options, headers,
    and query parameters cannot fall through to an event payload.
    """

    if not isinstance(command, str):
        raise TypeError("command must be a string")
    summary = " ".join(command.strip().split())
    summary = re.sub(
        re.escape(_BASH_GUARD_FACT_MARKER),
        "<redacted>",
        summary,
        flags=re.IGNORECASE,
    )

    summary = _COMMAND_URL_USERINFO.sub(
        lambda match: f"{match.group('scheme')}<redacted>@",
        summary,
    )
    summary = _COMMAND_AUTH_HEADER.sub(
        lambda match: f"{match.group('prefix')}<redacted>",
        summary,
    )
    summary = _COMMAND_QUERY_SECRET.sub(
        lambda match: f"{match.group('prefix')}<redacted>",
        summary,
    )
    summary = _COMMAND_AUTH_OPTION.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('separator')}"
            f"{_redact_quoted_value(match.group('value'))}"
        ),
        summary,
    )
    summary = _COMMAND_SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}{_redact_quoted_value(match.group('value'))}",
        summary,
    )
    summary = _BEARER_SECRET.sub("Bearer <redacted>", summary)
    summary = _BARE_API_KEY.sub("<redacted>", summary)
    if len(summary) > 240:
        return summary[:239] + "…"
    return summary


__all__ = ["safe_bash_command_summary"]
