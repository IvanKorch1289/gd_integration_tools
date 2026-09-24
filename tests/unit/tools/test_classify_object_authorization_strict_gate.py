"""Meta-test: classify_object_authorization --strict gate (v6 W1).

Per v6 W1: «Object classifier strict должен падать при `unknown > 0`».
Gate MUST exit non-zero при любом unknown callsite (не threshold 20% как
раньше — скрывало 23 unknown).

Regression guard: тест запускает script как subprocess + проверяет exit
code + stderr message. Если кто-то ослабит strict gate (revert на 20%
threshold) — тест упадёт.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_strict() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/classify_object_authorization.py", "--strict"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_strict_gate_fails_on_unknown_callsites() -> None:
    """v6 W1: gate exits 1 если any unknown > 0.

    На текущий момент в проекте 23 unknown callsites — gate ДОЛЖЕН
    падать (ранее был threshold 20% — gate проходил с exit 0).
    """
    result = _run_strict()

    assert result.returncode != 0, (
        f"strict gate PASSED but should FAIL per v6 W1 (unknown > 0). "
        f"stdout tail:\n{result.stdout[-500:]}\n"
        f"stderr:\n{result.stderr[-500:]}"
    )

    # Stderr должен содержать explicit FAILURE message + unknown count.
    assert "FAILED" in result.stderr, (
        f"strict gate failed (exit={result.returncode}) but stderr "
        f"missing FAILED message:\n{result.stderr[-500:]}"
    )
    assert "unknown callsites" in result.stderr, (
        f"strict gate failed but stderr missing unknown count:\n{result.stderr[-500:]}"
    )

    # Парсим число unknown callsites для sanity-check (должно быть > 0).
    match = re.search(r"(\d+) unknown callsites", result.stderr)
    assert match is not None, f"cannot parse unknown count: {result.stderr}"
    n_unknown = int(match.group(1))
    assert n_unknown > 0, (
        f"strict gate failed but parsed 0 unknown callsites — "
        f"either regex bug или actual state изменился. stderr:\n"
        f"{result.stderr[-500:]}"
    )


def test_strict_gate_help_documents_v6_thresholds() -> None:
    """Help text должен document новый v6 порог (unknown > 0)."""
    result = subprocess.run(
        [sys.executable, "tools/classify_object_authorization.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "unknown" in result.stdout.lower()
    # Per v6 W1 — gate должен block на unknown > 0 (НЕ threshold 20%).
    assert "20" not in result.stdout or "v6" in result.stdout, (
        "Help text references 20% threshold (deprecated per v6 W1)"
    )
