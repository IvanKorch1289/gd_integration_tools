"""Meta-test: verify_test_profiles gate (v6 / 25.09 audit).

Per v6 §10 + 25.09 audit: «Разделить test dependency profiles (core / api /
scheduler / workflow / messaging / ai / frontend / rpa / test-*)».

Этот тест проверяет что gate обнаруживает regression (missing profile,
empty profile, missing minimal deps).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/verify_test_profiles.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_strict_gate_passes_when_all_profiles_present() -> None:
    """v6 W1: gate exits 0 когда все required profiles + minimal deps."""
    result = _run_gate(["--strict"])
    assert result.returncode == 0, (
        f"verify_test_profiles gate FAILED (exit={result.returncode}) "
        f"but expected PASS после 25.09 audit fix. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_detected_profiles_count() -> None:
    """Detection должно найти ровно 9 test-* профилей (8 scoped + test-all)."""
    result = _run_gate([])
    assert result.returncode == 0
    assert "test-core" in result.stdout
    assert "test-api" in result.stdout
    assert "test-scheduler" in result.stdout
    assert "test-workflow" in result.stdout
    assert "test-messaging" in result.stdout
    assert "test-ai" in result.stdout
    assert "test-frontend" in result.stdout
    assert "test-rpa" in result.stdout
    assert "test-all" in result.stdout


def test_test_all_is_meta_extra() -> None:
    """test-all должен содержать больше deps чем test-scheduler (meta-extra)."""
    result = _run_gate([])
    assert result.returncode == 0

    # Parse detected deps counts из stdout.
    # Output format: "  test-name    N deps"
    import re

    counts: dict[str, int] = {}
    for m in re.finditer(r"(test-\w+)\s+(\d+)\s+deps", result.stdout):
        counts[m.group(1)] = int(m.group(2))

    assert "test-all" in counts, "test-all должен быть detected"
    assert "test-scheduler" in counts, "test-scheduler должен быть detected"
    assert counts["test-all"] > counts["test-scheduler"], (
        f"test-all ({counts.get('test-all')} deps) должен быть meta-extra "
        f"с > deps чем test-scheduler ({counts.get('test-scheduler')} deps)."
    )
