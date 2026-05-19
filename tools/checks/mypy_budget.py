"""Mypy budget gate (Sprint 9 K2 W6 + DoD-12).

Запускает mypy, считает уникальные ошибки, fail'ит если их больше
``MAX_MYPY_ERRORS`` (ratcheting baseline). При успехе автоматически
обновляет ``.mypy-baseline.json`` с новым (меньшим) значением.

Запуск:

.. code-block:: bash

    python tools/checks/mypy_budget.py --max 30
    # exit 0 — ok (errors <= max)
    # exit 1 — превышен budget

Idea: budget уменьшается со временем (S9: 30, S10: 25, S11: 15, S12: 0).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = ROOT / ".mypy-baseline.json"

# Cтрока ошибки mypy: ``path/to/file.py:NN: error: ...``
ERROR_RE = re.compile(r"^[^:]+:\d+:\s*(?:\d+:\s*)?error:", re.MULTILINE)


def run_mypy() -> tuple[int, str]:
    """Запускает mypy и возвращает (exit_code, combined_stdout_stderr)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-m",
            "mypy",
            "--cache-dir=/dev/null",
            "-p",
            "src",
        ],
        capture_output=True,
        text=True,
        env={"MYPY_USE_MYPYC": "0", **_env()},
    )
    return proc.returncode, proc.stdout + proc.stderr


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


def count_errors(output: str) -> int:
    return len(ERROR_RE.findall(output))


def load_baseline() -> int | None:
    if not BASELINE_FILE.exists():
        return None
    try:
        return int(json.loads(BASELINE_FILE.read_text()).get("errors"))
    except (ValueError, KeyError):
        return None


def save_baseline(errors: int) -> None:
    BASELINE_FILE.write_text(
        json.dumps({"errors": errors, "tool": "mypy"}, indent=2) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max",
        type=int,
        default=30,
        help="абсолютный budget (default 30)",
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help="обновить baseline если errors уменьшились",
    )
    args = parser.parse_args()

    print("Running mypy...")
    code, output = run_mypy()
    errors = count_errors(output)
    baseline = load_baseline()

    print(f"mypy errors: {errors} (max={args.max}, baseline={baseline})")

    if errors > args.max:
        print(
            f"FAIL: {errors} errors exceeds budget {args.max}",
            file=sys.stderr,
        )
        return 1

    if baseline is not None and errors > baseline:
        print(
            f"FAIL: {errors} errors > baseline {baseline} "
            f"(ratcheting: запрещено ухудшать)",
            file=sys.stderr,
        )
        return 1

    if args.ratchet and (baseline is None or errors < baseline):
        save_baseline(errors)
        print(f"baseline updated: {errors}")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
