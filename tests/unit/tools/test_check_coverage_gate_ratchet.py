"""Regression tests для coverage-gate flags (Sprint 41 W1 Item 5).

Покрывает:
1. \`--update-ratchet\` flag bumps coverage_percent + appends ratchet_history.
2. \`--sprint-label\` flag customizes ratchet entry label.
3. \`per-layer --strict\` flag enables CI enforcement (exit-1 on fail).
4. \`per-layer\` without \`--strict\` is informational only (exit-0 always).
5. ratchet_history dedup per (date, sprint) tuple.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def tmp_baseline(tmp_path: Path) -> Path:
    """Create temporary baseline file."""
    baseline = tmp_path / "coverage.json"
    baseline.write_text(
        json.dumps(
            {
                "coverage_percent": 60.0,
                "threshold": 60.0,
                "phase_1_complete_run": {"aggregate": {"percent": 60.0}},
            }
        ),
        encoding="utf-8",
    )
    return baseline


@pytest.fixture
def fake_coverage_xml(tmp_path: Path) -> Path:
    """Create fake coverage.xml with 62% line-rate."""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        '<?xml version="1.0" ?>\n'
        '<coverage version="7.15.3" timestamp="1787825573361" '
        'lines-valid="1000" lines-covered="620" line-rate="0.62">\n'
        "<sources><source><path>/test/src/backend</path></source></sources>\n"
        "</coverage>\n",
        encoding="utf-8",
    )
    return xml_path


class TestUpdateRatchetFlag:
    """\`--update-ratchet\` flag bumps coverage_percent + appends history."""

    def test_update_ratchet_bumps_coverage_percent(
        self, tmp_baseline: Path, fake_coverage_xml: Path
    ) -> None:
        """Coverage 60% → 62% после --update-ratchet (fake XML has line-rate=0.62)."""
        result = subprocess.run(
            [
                sys.executable,
                "tools/check_coverage_gate.py",
                "main",
                "--coverage-xml",
                str(fake_coverage_xml),
                "--baseline",
                str(tmp_baseline),
                "--update-ratchet",
                "--sprint-label",
                "S41_test",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        data = json.loads(tmp_baseline.read_text(encoding="utf-8"))
        assert data["coverage_percent"] == pytest.approx(62.0, abs=0.5), (
            f"coverage_percent should bump to ~62%, got {data['coverage_percent']}"
        )

    def test_update_ratchet_appends_history(
        self, tmp_baseline: Path, fake_coverage_xml: Path
    ) -> None:
        """ratchet_history array has 1 entry после --update-ratchet."""
        result = subprocess.run(
            [
                sys.executable,
                "tools/check_coverage_gate.py",
                "main",
                "--coverage-xml",
                str(fake_coverage_xml),
                "--baseline",
                str(tmp_baseline),
                "--update-ratchet",
                "--sprint-label",
                "S41_test",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        data = json.loads(tmp_baseline.read_text(encoding="utf-8"))
        assert "ratchet_history" in data
        assert len(data["ratchet_history"]) >= 1
        last = data["ratchet_history"][-1]
        assert last["sprint"] == "S41_test"
        assert last["percent"] == pytest.approx(62.0, abs=0.5)
        assert "date" in last

    def test_update_ratchet_dedup(
        self, tmp_baseline: Path, fake_coverage_xml: Path
    ) -> None:
        """2 consecutive --update-ratchet в один день НЕ дублируют entry."""
        for _ in range(2):
            subprocess.run(
                [
                    sys.executable,
                    "tools/check_coverage_gate.py",
                    "main",
                    "--coverage-xml",
                    str(fake_coverage_xml),
                    "--baseline",
                    str(tmp_baseline),
                    "--update-ratchet",
                    "--sprint-label",
                    "S41_test",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        data = json.loads(tmp_baseline.read_text(encoding="utf-8"))
        # Should still be only 1 entry (dedup per (date, sprint) tuple)
        assert len(data.get("ratchet_history", [])) == 1


class TestPerLayerStrictFlag:
    """\`per-layer --strict\` enables CI enforcement."""

    def test_per_layer_strict_returns_1_on_threshold_fail(
        self, fake_coverage_xml: Path, tmp_path: Path
    ) -> None:
        """Without per-layer thresholds file, exit 1 (threshold fail)."""
        # Write a thresholds file with a HIGH threshold (will fail).
        thresholds = tmp_path / "thresholds.txt"
        thresholds.write_text("core: 99\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "tools/check_coverage_gate.py",
                "per-layer",
                "--coverage-xml",
                str(fake_coverage_xml),
                "--thresholds",
                str(thresholds),
                "--strict",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1, (
            f"--strict должен exit 1 на threshold fail, got {result.returncode}. "
            f"stdout: {result.stdout}"
        )

    def test_per_layer_without_strict_informational(
        self, fake_coverage_xml: Path, tmp_path: Path
    ) -> None:
        """Without --strict, per-layer exit 0 даже при threshold fail (informational)."""
        thresholds = tmp_path / "thresholds.txt"
        thresholds.write_text("core: 99\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "tools/check_coverage_gate.py",
                "per-layer",
                "--coverage-xml",
                str(fake_coverage_xml),
                "--thresholds",
                str(thresholds),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"per-layer (без --strict) должен быть informational, exit 0. "
            f"got {result.returncode}. stderr: {result.stderr}"
        )


class TestUpdateRatchetCliIntegration:
    """CLI integration tests для --update-ratchet."""

    def test_cli_help_shows_update_ratchet_flag(self) -> None:
        """\`--help\` lists \`--update-ratchet\` flag (Sprint 41 W1 Item 5)."""
        result = subprocess.run(
            [sys.executable, "tools/check_coverage_gate.py", "main", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "--update-ratchet" in result.stdout, (
            f"ADR-0285 Item 5 flag missing from CLI help. Got: {result.stdout[:500]}"
        )
