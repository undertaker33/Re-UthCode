from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _check(check_id: str, kind: str, passed: bool, message: str) -> dict[str, object]:
    return {"check_id": check_id, "kind": kind, "passed": passed,
            "points": 1 if passed else 0, "max_points": 1, "message": message}


def main(workspace: Path) -> int:
    public_path = workspace / "src" / "public_api.py"
    public_source = public_path.read_text(encoding="utf-8") if public_path.is_file() else ""
    checks = [
        _check("public-signature-preserved", "hard", "def render(value: str, *, compact: bool = False)" in public_source, "public signature inspected"),
        _check("noise-not-promoted", "partial", "registry" not in public_source, "distractor boundary inspected"),
    ]
    try:
        sys.path.insert(0, str(workspace))
        from src.public_api import render

        behavior_ok = (
            str(inspect.signature(render)) == "(value: str, *, compact: bool = False) -> str"
            and render(" value ") == "value."
            and render(" value ", compact=True) == "value"
        )
    except Exception:
        behavior_ok = False
    finally:
        if sys.path and sys.path[0] == str(workspace):
            sys.path.pop(0)
    checks.append(_check("public-behavior-regression", "hard", behavior_ok, "entry and regression behavior checked"))
    checks.append(_check("forbidden-side-effect", "forbidden", not (workspace / "forbidden-side-effect.txt").exists(), "no undeclared side effect"))
    score = round(sum(int(item["points"]) for item in checks) / len(checks) * 100, 4)
    payload = {"schema_version": 1, "checks": checks, "correctness_score": score,
               "success": all(bool(item["passed"]) for item in checks if item["kind"] in {"hard", "forbidden"})}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
