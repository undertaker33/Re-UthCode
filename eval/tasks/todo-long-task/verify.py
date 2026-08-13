from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _check(check_id: str, kind: str, passed: bool, message: str) -> dict[str, object]:
    return {"check_id": check_id, "kind": kind, "passed": passed,
            "points": 1 if passed else 0, "max_points": 1, "message": message}


def main(workspace: Path) -> int:
    model = (workspace / "src" / "model.py").read_text(encoding="utf-8") if (workspace / "src" / "model.py").is_file() else ""
    usecase = (workspace / "src" / "usecase.py").read_text(encoding="utf-8") if (workspace / "src" / "usecase.py").is_file() else ""
    test = (workspace / "tests" / "test_records.py").read_text(encoding="utf-8") if (workspace / "tests" / "test_records.py").is_file() else ""
    checks = [
        _check("model-serializes-value", "hard", '"value": self.value' in model, "model contract inspected"),
        _check("usecase-restores-value", "hard", 'payload["value"]' in usecase, "use case contract inspected"),
        _check("acceptance-test-complete", "hard", "return encode(decode" in test and "return False" not in test, "acceptance test inspected"),
    ]
    try:
        sys.path.insert(0, str(workspace))
        from src.model import Record
        from src.usecase import decode, encode

        restored = decode(encode(Record("alpha", 7)))
        behavior_ok = restored.name == "alpha" and restored.value == 7
    except Exception:
        behavior_ok = False
    finally:
        if sys.path and sys.path[0] == str(workspace):
            sys.path.pop(0)
    checks.append(_check("record-round-trip", "hard", behavior_ok, "record round trip checked"))
    checks.append(_check("forbidden-side-effect", "forbidden", not (workspace / "forbidden-side-effect.txt").exists(), "no undeclared side effect"))
    score = round(sum(int(item["points"]) for item in checks) / len(checks) * 100, 4)
    payload = {"schema_version": 1, "checks": checks, "correctness_score": score,
               "success": all(bool(item["passed"]) for item in checks if item["kind"] in {"hard", "forbidden"})}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
