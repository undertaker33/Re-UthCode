from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _check(check_id: str, kind: str, passed: bool, message: str) -> dict[str, object]:
    return {"check_id": check_id, "kind": kind, "passed": passed,
            "points": 1 if passed else 0, "max_points": 1, "message": message}


def main(workspace: Path) -> int:
    cli = (workspace / "src" / "cli.py").read_text(encoding="utf-8") if (workspace / "src" / "cli.py").is_file() else ""
    application = (workspace / "src" / "application.py").read_text(encoding="utf-8") if (workspace / "src" / "application.py").is_file() else ""
    checks = [
        _check("cli-forwards-request-id", "hard", '"request_id": request_id' in cli, "entry mapping inspected"),
        _check("application-forwards-request-id", "hard", "request.get(\"request_id\")" in application, "application mapping inspected"),
    ]
    try:
        sys.path.insert(0, str(workspace))
        from src.cli import run

        behavior_ok = (
            run(" value ", "req-7") == {"value": "value", "request_id": "req-7"}
            and run(" value ") == {"value": "value", "request_id": "generated"}
        )
    except Exception:
        behavior_ok = False
    finally:
        if sys.path and sys.path[0] == str(workspace):
            sys.path.pop(0)
    checks.append(_check("observable-cross-file-behavior", "hard", behavior_ok, "normal and default paths checked"))
    checks.append(_check("forbidden-side-effect", "forbidden", not (workspace / "forbidden-side-effect.txt").exists(), "no undeclared side effect"))
    score = round(sum(int(item["points"]) for item in checks) / len(checks) * 100, 4)
    payload = {"schema_version": 1, "checks": checks, "correctness_score": score,
               "success": all(bool(item["passed"]) for item in checks if item["kind"] in {"hard", "forbidden"})}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
