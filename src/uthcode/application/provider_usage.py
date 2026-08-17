"""Safe projections of Provider Usage for Application diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from uthcode.core.provider import Usage


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _lookup(value: Mapping[str, object], path: Sequence[str]) -> tuple[bool, object]:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _cache_metric(
    details: Mapping[str, object],
    normalized: int,
    paths: Sequence[tuple[str, ...]],
) -> dict[str, object]:
    for path in paths:
        present, value = _lookup(details, path)
        evidence = _non_negative_int(value) if present else None
        if evidence is not None:
            return {
                "status": "available",
                # ``details`` proves that the Provider mapper reported this
                # metric.  The normalized counter is the authoritative value
                # after AgentLoop aggregation; details may describe only the
                # most recent Provider iteration.
                "tokens": normalized,
                "provenance": "usage.details." + ".".join(path),
            }
    # A non-zero normalized value is itself evidence that the mapper observed
    # a cache field.  Zero without field evidence remains not_available so the
    # Usage model's default does not masquerade as a provider measurement.
    if normalized > 0:
        return {
            "status": "available",
            "tokens": normalized,
            "provenance": "usage.cache_tokens",
        }
    return {"status": "not_available", "tokens": None, "provenance": None}


def public_usage_diagnostics(usage: Usage | None) -> dict[str, object]:
    """Project only measured token counters and cache field provenance.

    Provider-native ``Usage.details`` is intentionally inspected but never
    returned.  ``None`` and an empty default ``Usage`` mean that no provider
    measurement is available.
    """

    if not isinstance(usage, Usage):
        return {
            "status": "not_available",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cache_read": _cache_metric({}, 0, ()),
            "cache_write": _cache_metric({}, 0, ()),
        }
    details = usage.details if isinstance(usage.details, Mapping) else {}
    usage_observed = (
        any(key in details for key in ("input_tokens", "output_tokens", "total_tokens"))
        or usage.input_tokens > 0
        or usage.output_tokens > 0
    )
    cache_read = _cache_metric(
        details,
        usage.cache_read_tokens,
        (
            ("cache_read_input_tokens",),
            ("cache_read_tokens",),
            ("input_tokens_details", "cached_tokens"),
            ("prompt_tokens_details", "cached_tokens"),
        ),
    )
    cache_write = _cache_metric(
        details,
        usage.cache_write_tokens,
        (
            ("cache_creation_input_tokens",),
            ("cache_write_tokens",),
            ("input_tokens_details", "cache_write_tokens"),
            ("prompt_tokens_details", "cache_write_tokens"),
        ),
    )
    observed = usage_observed or cache_read["status"] == "available" or cache_write["status"] == "available"
    return {
        "status": "available" if observed else "not_available",
        "input_tokens": usage.input_tokens if usage_observed else None,
        "output_tokens": usage.output_tokens if usage_observed else None,
        "total_tokens": usage.total_tokens if usage_observed else None,
        "cache_read": cache_read,
        "cache_write": cache_write,
    }


__all__ = ["public_usage_diagnostics"]
