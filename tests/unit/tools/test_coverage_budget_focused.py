"""Focused tests for ``tools/checks/coverage_budget.py`` (Wave 4 P3.16)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Import the module under test.
from tools.checks import coverage_budget as cb


@pytest.fixture
def clean_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Clean baseline and coverage.json перед каждым test."""
    monkeypatch.setattr(cb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cb, "BASELINE_FILE", tmp_path / ".baselines" / "coverage.json")
    monkeypatch.setattr(cb, "COVERAGE_JSON", tmp_path / "coverage.json")
    monkeypatch.setattr(cb, "COVERAGE_XML", tmp_path / "coverage.xml")
    return tmp_path


class TestReadBaseline:
    def test_no_baseline(self, clean_baseline: Path) -> None:
        assert cb._read_baseline() == 0.0

    def test_with_baseline(self, clean_baseline: Path) -> None:
        cb._write_baseline(72.5)
        assert cb._read_baseline() == 72.5


class TestReadCurrentCoverage:
    def test_no_coverage_file(self, clean_baseline: Path) -> None:
        assert cb._read_current_coverage() is None

    def test_valid_coverage_json(self, clean_baseline: Path) -> None:
        cov_file = clean_baseline / "coverage.json"
        cov_data = {
            "totals": {
                "percent_covered": 75.5,
                "covered_lines": 100,
                "num_statements": 200,
            }
        }
        cov_file.write_text(json.dumps(cov_data), encoding="utf-8")
        assert cb._read_current_coverage() == 75.5

    def test_malformed_coverage(self, clean_baseline: Path) -> None:
        (clean_baseline / "coverage.json").write_text("not json{", encoding="utf-8")
        assert cb._read_current_coverage() is None


class TestMain:
    def test_report_only_no_coverage_data(self, clean_baseline: Path) -> None:
        """Without coverage.json, exits 1 (no --report-only flag)."""
        from tools.checks.coverage_budget import cli as cb_cli

        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget"]
            with pytest.raises(SystemExit) as exc:
                cb_cli()
            assert exc.value.code == 1
        finally:
            sys.argv = original_argv

    def test_pass_with_min_satisfied(self, clean_baseline: Path) -> None:
        """Current ≥ min → returns 0 (or sys.exit 0 without --report-only)."""
        from tools.checks.coverage_budget import cli as cb_main

        cov_data = {"totals": {"percent_covered": 75.0}}
        (clean_baseline / "coverage.json").write_text(
            json.dumps(cov_data), encoding="utf-8"
        )
        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget", "--min", "60", "--report-only"]
            with pytest.raises(SystemExit) as exc:
                cb_main()
            assert exc.value.code == 0
        finally:
            sys.argv = original_argv

    def test_fail_with_min_not_satisfied(self, clean_baseline: Path) -> None:
        """Current < min → exit 1 (no --report-only)."""
        from tools.checks.coverage_budget import cli as cb_main

        cov_data = {"totals": {"percent_covered": 50.0}}
        (clean_baseline / "coverage.json").write_text(
            json.dumps(cov_data), encoding="utf-8"
        )
        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget", "--min", "60"]
            with pytest.raises(SystemExit) as exc:
                cb_main()
            assert exc.value.code == 1
        finally:
            sys.argv = original_argv

    def test_update_baseline_ratchets_up(self, clean_baseline: Path) -> None:
        """--update-baseline succeeds when current > baseline."""
        from tools.checks.coverage_budget import cli as cb_main

        cov_data = {"totals": {"percent_covered": 85.0}}
        (clean_baseline / "coverage.json").write_text(
            json.dumps(cov_data), encoding="utf-8"
        )
        cb._write_baseline(50.0)
        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget", "--update-baseline"]
            with pytest.raises(SystemExit) as exc:
                cb_main()
            assert exc.value.code == 0
            assert cb._read_baseline() == 85.0
        finally:
            sys.argv = original_argv

    def test_update_baseline_rejects_decrease(self, clean_baseline: Path) -> None:
        """--update-baseline fails when current ≤ baseline (ratchet up only)."""
        from tools.checks.coverage_budget import cli as cb_main

        cov_data = {"totals": {"percent_covered": 50.0}}
        (clean_baseline / "coverage.json").write_text(
            json.dumps(cov_data), encoding="utf-8"
        )
        cb._write_baseline(60.0)
        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget", "--update-baseline"]
            with pytest.raises(SystemExit) as exc:
                cb_main()
            assert exc.value.code == 1
        finally:
            sys.argv = original_argv

    def test_pass_with_baseline_from_file(self, clean_baseline: Path) -> None:
        """Uses stored baseline when --min not given."""
        from tools.checks.coverage_budget import cli as cb_main

        cov_data = {"totals": {"percent_covered": 75.0}}
        (clean_baseline / "coverage.json").write_text(
            json.dumps(cov_data), encoding="utf-8"
        )
        cb._write_baseline(60.0)
        original_argv = sys.argv
        try:
            sys.argv = ["coverage_budget"]
            with pytest.raises(SystemExit) as exc:
                cb_main()
            assert exc.value.code == 0
        finally:
            sys.argv = original_argv


class TestWriteBaseline:
    def test_write_creates_dir(self, clean_baseline: Path) -> None:
        cb._write_baseline(85.5)
        assert (clean_baseline / ".baselines" / "coverage.json").exists()
        content = (clean_baseline / ".baselines" / "coverage.json").read_text()
        assert "85.5" in content


class TestExports:
    def test_main_function_exists(self) -> None:
        assert callable(cb.main)
        assert callable(cb._read_baseline)
        assert callable(cb._write_baseline)
        assert callable(cb._read_current_coverage)
