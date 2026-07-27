"""Tests for :mod:`src.backend.core.ai.security.workflow_hooks`.

Coverage:
- ``rpa_browser_hook`` blocks only paths that resolve inside any stdlib
  temp root (``tempfile.gettempdir`` + ``/var/tmp``), with no
  hardcoded string matching (regression test for the F841/S108 audit).
- Non-temp paths are still allowed.
- Outside ``rpa.*`` workflow scope the hook is a no-op.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.core.ai.security.workflow_hooks import rpa_browser_hook


class TestRpaBrowserHookTempRoots:
    def test_blocks_tempdir_path(self, tmp_path: Path) -> None:
        inside = tmp_path / "downloads" / "report.pdf"
        inside.parent.mkdir(parents=True, exist_ok=True)
        inside.write_text("x")
        ctx = {"workflow": "rpa.download", "file_path": str(inside)}
        decision = rpa_browser_hook("u", ctx)
        assert decision.allowed is False
        assert "file_path_not_allowed" in decision.reason

    def test_blocks_var_tmp_path(self) -> None:
        # Construct a path that resolves into /var/tmp without assuming
        # it actually exists.
        candidate = Path("/var/tmp/gd_rpa_test_xxx.txt")
        ctx = {"workflow": "rpa.download", "file_path": str(candidate)}
        decision = rpa_browser_hook("u", ctx)
        assert decision.allowed is False

    def test_allows_non_temp_path(self) -> None:
        # Use /var/lib (a non-temp standard location) to verify the
        # hook only blocks tempdir-rooted paths, not everything.
        ctx = {"workflow": "rpa.download", "file_path": "/var/lib/gd_rpa/x"}
        decision = rpa_browser_hook("u", ctx)
        assert decision.allowed is True

    def test_outside_rpa_workflow_is_noop(self) -> None:
        # Any path, even a temp one, is allowed if the workflow prefix
        # is not rpa.* — the hook's responsibility is rpa-only.
        ctx = {
            "workflow": "banking.transaction",
            "file_path": str(tempfile.gettempdir()),
        }
        decision = rpa_browser_hook("u", ctx)
        assert decision.allowed is True

    def test_missing_file_path_is_noop(self) -> None:
        ctx = {"workflow": "rpa.download"}  # no file_path
        decision = rpa_browser_hook("u", ctx)
        assert decision.allowed is True
