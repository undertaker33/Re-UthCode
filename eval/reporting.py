"""Aggregation, compatibility checking and human-readable Eval reports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

from eval.metrics import DIMENSIONS
from eval.models import AttemptRecord, MetricStatus, VerifierResult


_REQUIRED_FINGERPRINTS = (
    "code",
    "task",
    "model",
    "model_id",
    "provider",
    "prompt",
    "config",
    "permission",
    "run_args",
    "platform",
    "runtime",
    "uthcode_revision",
)


def _plain(value: object) -> dict[str, object] | None:
    if isinstance(value, AttemptRecord):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else None
    return None


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_detail(attempt: Mapping[str, object], dimension: str) -> Mapping[str, object] | None:
    details = attempt.get("metric_details")
    if isinstance(details, Mapping):
        item = details.get(dimension)
        if isinstance(item, Mapping):
            return item
    metrics = attempt.get("metrics")
    if isinstance(metrics, Mapping):
        item = metrics.get(dimension)
        if isinstance(item, Mapping):
            status = item.get("status")
            value = item.get("value")
            return {
                "status": status,
                "score": value,
                "raw": {},
                "evidence_refs": item.get("evidence_refs", ()),
            }
    return None


def _aggregate_dimension(attempts: Sequence[Mapping[str, object]], dimension: str) -> dict[str, object]:
    details = [_metric_detail(attempt, dimension) for attempt in attempts]
    available = [item for item in details if item is not None and item.get("status") == MetricStatus.AVAILABLE.value]
    scores = [score for item in available if (score := _numeric(item.get("score"))) is not None]
    raw = [item.get("raw", {}) for item in available]
    evidence = sorted({
        str(ref)
        for item in available
        for ref in item.get("evidence_refs", ())
        if isinstance(item.get("evidence_refs", ()), Sequence)
    })
    if not available or not scores:
        return {
            "status": MetricStatus.NOT_AVAILABLE.value,
            "scores": [],
            "median_score": None,
            "mean_score": None,
            "raw": raw,
            "evidence_refs": evidence,
            "available_count": len(available),
            "sample_count": len(attempts),
        }
    return {
        "status": MetricStatus.AVAILABLE.value,
        "scores": scores,
        "median_score": median(scores),
        "mean_score": sum(scores) / len(scores),
        "raw": raw,
        "evidence_refs": evidence,
        "available_count": len(available),
        "sample_count": len(attempts),
    }


def _fingerprint_summary(attempts: Sequence[Mapping[str, object]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    keys = sorted({
        str(key)
        for attempt in attempts
        for key in (attempt.get("fingerprints", {}) if isinstance(attempt.get("fingerprints"), Mapping) else {})
    })
    values: dict[str, list[str]] = {}
    for key in keys:
        values[key] = sorted({
            str(attempt["fingerprints"][key])
            for attempt in attempts
            if isinstance(attempt.get("fingerprints"), Mapping) and key in attempt["fingerprints"]
        })
    summary = {key: vals[0] for key, vals in values.items() if len(vals) == 1}
    for key, vals in values.items():
        if len(vals) != 1:
            summary[key] = "<varies>"
    return summary, values


def _task_sample_counts(attempts: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        task_id = str(attempt.get("task_id")) if attempt.get("task_id") is not None else "<missing>"
        counts[task_id] = counts.get(task_id, 0) + 1
    return dict(sorted(counts.items()))


def _valid_task_sample_counts(report: Mapping[str, object]) -> bool:
    value = report.get("task_sample_counts")
    task_ids = report.get("task_ids")
    sample_count = report.get("sample_count")
    if not isinstance(value, Mapping) or not value:
        return False
    if not isinstance(task_ids, list) or not task_ids:
        return False
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= 0:
        return False
    if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
        return False
    if len(set(task_ids)) != len(task_ids):
        return False
    if set(value) != set(task_ids):
        return False
    if any(
        not isinstance(key, str)
        or not key
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
        for key, count in value.items()
    ):
        return False
    return sum(value.values()) == sample_count


def aggregate_experiment(experiment_id: str, attempts: Sequence[object]) -> dict[str, object]:
    """Aggregate attempt records without producing a cross-dimension total."""

    normalized = [value for value in (_plain(item) for item in attempts) if value is not None]
    fingerprints, variants = _fingerprint_summary(normalized)
    task_sample_counts = _task_sample_counts(normalized)
    task_ids = sorted(task_sample_counts)
    finish_categories: dict[str, int] = {}
    for item in normalized:
        category = str(item.get("finish_category", "unknown"))
        finish_categories[category] = finish_categories.get(category, 0) + 1
    dimensions = {dimension: _aggregate_dimension(normalized, dimension) for dimension in DIMENSIONS}
    safety = dimensions["safety"]
    safety_hard_failures = sum(
        1
        for item in normalized
        for raw in ([_metric_detail(item, "safety")] if _metric_detail(item, "safety") is not None else [])
        if isinstance(raw, Mapping) and isinstance(raw.get("raw"), Mapping) and raw["raw"].get("hard_failure") is True
    )
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "sample_count": len(normalized),
        "task_ids": task_ids,
        "task_sample_counts": task_sample_counts,
        "fingerprints": fingerprints,
        "fingerprint_variants": variants,
        "finish_categories": finish_categories,
        "dimensions": dimensions,
        "safety_hard_failure_count": safety_hard_failures,
        "attempts": normalized,
    }


def compare_experiments(baseline: Mapping[str, object], candidate: Mapping[str, object]) -> dict[str, object]:
    """Compare only compatible experiments; incompatible results have no delta."""

    incompatibilities: list[str] = []
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        fingerprints = report.get("fingerprints")
        if not isinstance(fingerprints, Mapping):
            incompatibilities.append(f"{label}.fingerprints")
            continue
        for key in _REQUIRED_FINGERPRINTS:
            if key not in fingerprints:
                incompatibilities.append(f"{label}.fingerprints.{key}")
        variants = report.get("fingerprint_variants")
        if not isinstance(variants, Mapping):
            incompatibilities.append(f"{label}.fingerprint_variants")
    baseline_fingerprints = baseline.get("fingerprints")
    candidate_fingerprints = candidate.get("fingerprints")
    if baseline_fingerprints != candidate_fingerprints:
        all_keys = sorted({
            *(
                baseline_fingerprints.keys()
                if isinstance(baseline_fingerprints, Mapping)
                else ()
            ),
            *(
                candidate_fingerprints.keys()
                if isinstance(candidate_fingerprints, Mapping)
                else ()
            ),
        })
        for key in all_keys:
            left = baseline_fingerprints.get(key) if isinstance(baseline_fingerprints, Mapping) else None
            right = candidate_fingerprints.get(key) if isinstance(candidate_fingerprints, Mapping) else None
            if left != right:
                incompatibilities.append(f"fingerprints.{key}")
    if baseline.get("task_ids") != candidate.get("task_ids"):
        incompatibilities.append("task_ids")
    if baseline.get("sample_count") != candidate.get("sample_count"):
        incompatibilities.append("sample_count")
    baseline_task_counts = baseline.get("task_sample_counts")
    candidate_task_counts = candidate.get("task_sample_counts")
    if not _valid_task_sample_counts(baseline):
        incompatibilities.append("baseline.task_sample_counts")
    if not _valid_task_sample_counts(candidate):
        incompatibilities.append("candidate.task_sample_counts")
    if (
        _valid_task_sample_counts(baseline)
        and _valid_task_sample_counts(candidate)
        and dict(baseline_task_counts) != dict(candidate_task_counts)  # type: ignore[arg-type]
    ):
        incompatibilities.append("task_sample_counts")
    if baseline.get("schema_version") != candidate.get("schema_version"):
        incompatibilities.append("schema_version")
    baseline_variants = baseline.get("fingerprint_variants")
    candidate_variants = candidate.get("fingerprint_variants")
    if isinstance(baseline_variants, Mapping) and isinstance(candidate_variants, Mapping):
        for key in sorted(set(baseline_variants) | set(candidate_variants)):
            left = baseline_variants.get(key)
            right = candidate_variants.get(key)
            if left != right:
                incompatibilities.append(f"fingerprint_variants.{key}")
    if incompatibilities:
        return {
            "schema_version": 1,
            "compatible": False,
            "incompatibilities": incompatibilities,
            "delta": None,
        }

    delta: dict[str, object] = {}
    baseline_dimensions = baseline.get("dimensions", {})
    candidate_dimensions = candidate.get("dimensions", {})
    for dimension in DIMENSIONS:
        left = baseline_dimensions.get(dimension, {}) if isinstance(baseline_dimensions, Mapping) else {}
        right = candidate_dimensions.get(dimension, {}) if isinstance(candidate_dimensions, Mapping) else {}
        left_score = _numeric(left.get("median_score")) if isinstance(left, Mapping) else None
        right_score = _numeric(right.get("median_score")) if isinstance(right, Mapping) else None
        delta[dimension] = {
            "median_score": None if left_score is None or right_score is None else right_score - left_score,
            "baseline_median_score": left_score,
            "candidate_median_score": right_score,
            "absolute_difference": None if left_score is None or right_score is None else abs(right_score - left_score),
            "delta": None if left_score is None or right_score is None else right_score - left_score,
        }
    return {"schema_version": 1, "compatible": True, "incompatibilities": [], "delta": delta}


def render_markdown_report(report: Mapping[str, object]) -> str:
    dimensions = report.get("dimensions", {})
    lines = [
        f"# Eval experiment `{report.get('experiment_id', '<unknown>')}`",
        "",
        f"Samples: `{report.get('sample_count', 0)}`",
        f"Task sample counts: `{json.dumps(report.get('task_sample_counts', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
        "| Dimension | Status | Median score | Available |",
        "| --- | --- | ---: | ---: |",
    ]
    for dimension in DIMENSIONS:
        item = dimensions.get(dimension, {}) if isinstance(dimensions, Mapping) else {}
        lines.append(
            f"| `{dimension}` | `{item.get('status', 'not_available')}` | "
            f"{item.get('median_score', '—')} | {item.get('available_count', 0)}/{item.get('sample_count', 0)} |"
        )
    lines.extend(["", "Safety hard failures: `" + str(report.get("safety_hard_failure_count", 0)) + "`", ""])
    return "\n".join(lines)


def render_terminal_summary(report: Mapping[str, object]) -> str:
    dimensions = report.get("dimensions", {})
    lines = [f"Eval {report.get('experiment_id', '<unknown>')} ({report.get('sample_count', 0)} samples)"]
    task_counts = report.get("task_sample_counts", {})
    if isinstance(task_counts, Mapping):
        lines.append(
            "task_samples: "
            + ", ".join(f"{task_id}={count}" for task_id, count in sorted(task_counts.items()))
        )
    for dimension in DIMENSIONS:
        item = dimensions.get(dimension, {}) if isinstance(dimensions, Mapping) else {}
        lines.append(
            f"{dimension}: {item.get('status', 'not_available')} "
            f"median={item.get('median_score', 'n/a')} "
            f"available={item.get('available_count', 0)}/{item.get('sample_count', 0)}"
        )
    lines.append(f"safety_hard_failures: {report.get('safety_hard_failure_count', 0)}")
    return "\n".join(lines)


def report_to_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


__all__ = [
    "aggregate_experiment",
    "compare_experiments",
    "render_markdown_report",
    "render_terminal_summary",
    "report_to_json",
]
