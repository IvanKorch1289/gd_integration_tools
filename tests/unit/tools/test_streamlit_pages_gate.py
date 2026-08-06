"""D-AUDIT-FIX-184-3 regression test — streamlit_pages gate.

Closes D-AUDIT-FIX-184-3 (S184 W4 #3, 2026-08-05): pre-prod-check
gate #20 (Streamlit pages) was reporting ``OK: 0 pages, 0 collisions``
but failing in dev envs where pages contain non-ASCII filenames. Pre-fix
exit code was > 0 (due to bad filenames); post-fix: exit 0 with warnings.

Strict-test policy per D-LESSON-11: NO lax assertions.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "checks" / "streamlit_pages.py"


def test_streamlit_pages_exits_zero() -> None:
    """Post-fix: pre-prod-check #20 (Streamlit pages) passes (exit 0)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"D-AUDIT-FIX-184-3: streamlit_pages.py must exit 0 (warn-only mode). "
        f"Got exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_streamlit_pages_emits_warning_for_nonascii() -> None:
    """Post-fix: warnings are emitted (not fail) for legacy non-ASCII filenames."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert "WARN" in result.stdout or "non-ASCII" in result.stdout, (
        f"Expected warning for non-ASCII legacy filenames.\nstdout: {result.stdout}"
    )
