"""Meta-test: check_privacy_lifecycle default exit behavior (v6 W1).

Per v6 W1: «Любой backend с ❌ должен давать ненулевой exit code».
Раньше default mode (без --strict) exits 0 даже с ❌ — gate FAIL-OPEN.

Regression guard: проверяет что gate сейчас fail-closed by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_privacy_lifecycle.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_default_mode_exits_0_when_no_issues() -> None:
    """На текущем коде все 5 backends covered → exit 0 (no issues)."""
    result = _run()

    assert result.returncode == 0, (
        f"Default mode FAIL (exit={result.returncode}) but all 5 backends "
        f"have erasure. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Parse JSON output — должно показать все 5 backends как covered.
    result_json = _run("--json")
    payload = json.loads(result_json.stdout)
    backends = payload["storage_coverage"]
    assert len(backends) == 5, (
        f"Expected 5 backends, got {len(backends)}: {list(backends.keys())}"
    )
    uncovered = [name for name, info in backends.items() if not info["covered"]]
    assert not uncovered, f"Expected all 5 backends covered, uncovered: {uncovered}"


def test_default_mode_fails_on_synthetic_issue() -> None:
    """Воспроизводим ошибку: monkeypatched backends с ❌ → gate exits 1.

    Per v6 W1: «Любой backend с ❌ должен давать ненулевой exit code».
    """
    # Inject a fake broken state через временный файл — без permanent
    # damage. Простой подход: проверить что gate's exit logic корректен
    # через `_check_storage_coverage` direct call.
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.checks import check_privacy_lifecycle

        # Monkeypatch: forced uncovered.
        original = check_privacy_lifecycle._check_storage_coverage

        def broken_check():
            return {
                "fake_backend": {
                    "covered": False,
                    "evidence": "synthetic ❌ for meta-test",
                }
            }

        check_privacy_lifecycle._check_storage_coverage = broken_check
        try:
            result = check_privacy_lifecycle.main([])
            assert result == 1, f"Default gate SHOULD exit 1 per v6 W1, got {result}"
        finally:
            check_privacy_lifecycle._check_storage_coverage = original
    finally:
        sys.path.pop(0)


def test_no_strict_opt_out_for_debug() -> None:
    """--no-strict flag существует для opt-out (для triage / debugging)."""
    # Просто проверить что flag не падает на import.
    result = _run("--no-strict")
    assert result.returncode == 0, (
        f"--no-strict failed unexpectedly: {result.stdout}\n{result.stderr}"
    )
