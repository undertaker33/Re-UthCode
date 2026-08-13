from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _check(check_id: str, kind: str, passed: bool, message: str) -> dict[str, object]:
    return {"check_id": check_id, "kind": kind, "passed": passed,
            "points": 1 if passed else 0, "max_points": 1, "message": message}


def main(workspace: Path) -> int:
    expected = {
        "src/entry.py": "def answer(value: str) -> str:\n    return value.strip()\n",
        "docs/constraints.md": "# Constraints\n\nThe public function signature must remain unchanged.\n",
        "tests/test_entry.py": "from src.entry import answer\n\n\ndef test_answer() -> None:\n    assert answer(\" value \") == \"value\"\n",
    }
    changed = any(
        not (workspace / relative).is_file()
        or (workspace / relative).read_text(encoding="utf-8") != content
        for relative, content in expected.items()
    )
    checks = [
        _check("fixture-unchanged", "hard", not changed, "read-only fixture hash checked"),
        _check("required-evidence-present", "hard", all((workspace / path).is_file() for path in ("src/entry.py", "docs/constraints.md", "tests/test_entry.py")), "required evidence paths checked"),
        _check("forbidden-write", "forbidden", not (workspace / "forbidden-side-effect.txt").exists(), "no write side effect"),
    ]
    # The expected content is versioned with the fixture; verification itself
    # never creates or updates a baseline file.
    score = round(sum(int(item["points"]) for item in checks) / len(checks) * 100, 4)
    payload = {"schema_version": 1, "checks": checks, "correctness_score": score,
               "success": all(bool(item["passed"]) for item in checks if item["kind"] in {"hard", "forbidden"})}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
