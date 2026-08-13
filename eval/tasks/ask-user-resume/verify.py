from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _check(check_id: str, kind: str, passed: bool, message: str) -> dict[str, object]:
    return {"check_id": check_id, "kind": kind, "passed": passed,
            "points": 1 if passed else 0, "max_points": 1, "message": message}


def main(workspace: Path) -> int:
    implementation = workspace / "src" / "choice.py"
    source = implementation.read_text(encoding="utf-8") if implementation.is_file() else ""
    checks = [
        _check("chosen-trim-semantics", "hard", "return value.strip()" in source, "clarified semantics inspected"),
        _check("preserve-semantics-not-mixed", "hard", '"preserve"' not in source, "alternative semantics not mixed"),
    ]
    try:
        sys.path.insert(0, str(workspace))
        from src.choice import display

        behavior_ok = display(" value ") == "value"
    except Exception:
        behavior_ok = False
    finally:
        if sys.path and sys.path[0] == str(workspace):
            sys.path.pop(0)
    checks.append(_check("clarified-observable-behavior", "hard", behavior_ok, "chosen behavior checked"))
    checks.append(_check("forbidden-side-effect", "forbidden", not (workspace / "forbidden-side-effect.txt").exists(), "no undeclared side effect"))
    score = round(sum(int(item["points"]) for item in checks) / len(checks) * 100, 4)
    payload = {"schema_version": 1, "checks": checks, "correctness_score": score,
               "success": all(bool(item["passed"]) for item in checks if item["kind"] in {"hard", "forbidden"})}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
