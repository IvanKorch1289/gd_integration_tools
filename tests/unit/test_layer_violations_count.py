"""Sprint 4 (partial) — characterization test для layer violations baseline.

TDD principle applied: tests describe the current state explicitly.
Refactor toward target count (167 → ~140) — multi-sprint effort.

This test FAILS if:
- New layer violations are added (drift detection)
- Allowlist is modified without justification

Tests do NOT enforce removal of violations — только freeze baseline +
detect drift. Real reduction — multi-sprint work per
MULTI_SPRINT_2026-08-17.md Sprint 4 roadmap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_FILE = REPO_ROOT / "tools" / "check_layers_allowlist.txt"


def _run_check_layers() -> subprocess.CompletedProcess[str]:
    """Run ``python tools/check_layers.py`` and capture output."""
    return subprocess.run(
        ["python", "tools/check_layers.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestLayerViolationsBaseline:
    """Freeze current state — drift detection."""

    def test_allowlist_file_exists(self) -> None:
        assert ALLOWLIST_FILE.exists(), (
            f"Allowlist file not found: {ALLOWLIST_FILE}. "
            f"Migration: re-run check_layers.py --update-allowlist."
        )

    def test_check_layers_runs_clean(self) -> None:
        """check_layers.py MUST exit 0 (no new violations)."""
        result = _run_check_layers()
        assert result.returncode == 0, (
            f"check_layers.py failed (exit {result.returncode}). "
            f"Output:\n{result.stdout}\n{result.stderr}"
        )

    def test_check_layers_reports_zero_new(self) -> None:
        """Output should say '0 новых' (zero new violations)."""
        result = _run_check_layers()
        assert "0 новых" in result.stdout or "0 new" in result.stdout, (
            f"check_layers.py output changed format. "
            f"Expected '0 новых' or '0 new'. Output:\n{result.stdout}"
        )

    def test_baseline_legacy_violations_documented(self) -> None:
        """Legacy baseline должна быть зафиксирована (167 per Phase 0)."""
        result = _run_check_layers()
        output = result.stdout
        # Baseline 167 — frozen per MULTI_SPRINT_2026-08-17.md.
        # Если значение изменилось — это signal либо drift, либо refactor.
        assert "baseline: 167 legacy" in output or "baseline: 167" in output, (
            f"Baseline changed from 167 — either drift (bad) or refactor (good, "
            f"should be documented in MULTI_SPRINT_2026-08-17.md). "
            f"Output:\n{output}"
        )


class TestLayerViolationsCountReduction:
    """Target: 167 → 140 (Sprint 4 roadmap). Multi-sprint effort."""

    def test_target_baseline_documented(self) -> None:
        """Roadmap target должен быть в MULTI_SPRINT_2026-08-17.md."""
        roadmap = REPO_ROOT / "docs" / "audit" / "MULTI_SPRINT_2026-08-17.md"
        assert roadmap.exists(), (
            f"Roadmap file not found: {roadmap}"
        )

        content = roadmap.read_text()
        # Sprint 4 target: 167 → 140
        assert "167" in content, (
            "MULTI_SPRINT_2026-08-17.md не содержит baseline reference (167)"
        )
        assert "140" in content, (
            "MULTI_SPRINT_2026-08-17.md не содержит Sprint 4 target (140)"
        )


class TestAllowlistFormat:
    """Allowlist format validation — prevent corruption."""

    def test_allowlist_has_header(self) -> None:
        lines = ALLOWLIST_FILE.read_text().splitlines()
        assert lines[0].startswith("#"), (
            f"Allowlist должен начинаться с header комментария. "
            f"First line: {lines[0]!r}"
        )

    def test_allowlist_entries_have_three_columns(self) -> None:
        """Each entry: <rel_path>\\t<layer>\\t<module>."""
        lines = ALLOWLIST_FILE.read_text().splitlines()
        bad_lines = [
            (i + 1, line)
            for i, line in enumerate(lines)
            if line and not line.startswith("#") and line.count("\t") != 2
        ]
        assert not bad_lines, (
            f"Allowlist entries должны иметь 3 колонки (tab-separated). "
            f"Bad lines:\n{bad_lines[:5]}"
        )

    def test_allowlist_entry_count_reasonable(self) -> None:
        """Allowlist shouldn't grow without bound — sanity check."""
        lines = ALLOWLIST_FILE.read_text().splitlines()
        entry_count = sum(
            1 for line in lines if line and not line.startswith("#")
        )
        assert 50 <= entry_count <= 250, (
            f"Allowlist entry count {entry_count} вне ожидаемого "
            f"диапазона 50-250. Investigate baseline drift."
        )