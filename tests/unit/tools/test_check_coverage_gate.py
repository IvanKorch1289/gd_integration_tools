"""Unit-тесты для ``tools/check_coverage_gate.py``.

Wave ``[wave:s6/k3-coverage-gate-70]``.

Покрытие:

* парсинг ``coverage.xml`` (cobertura формат);
* threshold-check (pass/fail);
* baseline drop detection (strict mode);
* baseline update flow;
* error-handling (missing file / invalid XML).
"""

# ruff: noqa: S101

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

TOOL_PATH = Path("tools/check_coverage_gate.py")
BASELINE_PATH = Path(".baselines/coverage.json")


def _write_coverage_xml(path: Path, line_rate: float) -> None:
    """Создаёт минимальный cobertura coverage.xml с указанным line-rate."""
    root = ET.Element(
        "coverage", {"line-rate": f"{line_rate:.4f}", "branch-rate": "0.50"}
    )
    ET.ElementTree(root).write(str(path))


def _run_gate(*args: str) -> subprocess.CompletedProcess:
    """Запускает CLI gate с заданными аргументами."""
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_tool_exists_and_help() -> None:
    """check_coverage_gate.py файл существует и поддерживает --help."""
    assert TOOL_PATH.exists()
    result = _run_gate("--help")
    assert result.returncode == 0
    assert "coverage" in result.stdout.lower()


def test_baseline_json_loadable() -> None:
    """.baselines/coverage.json — валидный JSON с обязательными полями."""
    assert BASELINE_PATH.exists()
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert "coverage_percent" in data
    assert "threshold" in data
    assert "target_threshold" in data
    # S19 K2 W4: threshold ratchet 70% → 75%
    assert data["target_threshold"] == 75.0


def test_gate_passes_when_above_threshold(tmp_path: Path) -> None:
    """Coverage 75% > threshold 50% → exit 0."""
    cov_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "baseline.json"
    _write_coverage_xml(cov_xml, 0.75)

    result = _run_gate(
        "--coverage-xml", str(cov_xml), "--baseline", str(baseline), "--threshold", "50"
    )
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_gate_fails_when_below_threshold(tmp_path: Path) -> None:
    """Coverage 45% < threshold 70% → exit 1."""
    cov_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "baseline.json"
    _write_coverage_xml(cov_xml, 0.45)

    result = _run_gate(
        "--coverage-xml", str(cov_xml), "--baseline", str(baseline), "--threshold", "70"
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr


def test_gate_error_when_xml_missing(tmp_path: Path) -> None:
    """Отсутствие coverage.xml → exit 2 (error)."""
    cov_xml = tmp_path / "missing.xml"
    result = _run_gate("--coverage-xml", str(cov_xml), "--threshold", "50")
    assert result.returncode == 2
    assert "ERROR" in result.stderr


def test_update_baseline_writes_snapshot(tmp_path: Path) -> None:
    """--update-baseline записывает текущий coverage в baseline.json."""
    cov_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "baseline.json"
    _write_coverage_xml(cov_xml, 0.65)

    result = _run_gate(
        "--coverage-xml",
        str(cov_xml),
        "--baseline",
        str(baseline),
        "--threshold",
        "50",
        "--update-baseline",
    )
    assert result.returncode == 0
    assert baseline.exists()
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["coverage_percent"] == pytest.approx(65.0, abs=0.01)
    # S19 K2 W4: _DEFAULT_THRESHOLD = 75.0 (ratcheted from 70)
    assert any("75" in t for t in data.get("next_wave_todo", []))


def test_strict_mode_detects_drop(tmp_path: Path) -> None:
    """Strict-mode: drop > 0.5% от baseline → exit 1."""
    cov_xml = tmp_path / "coverage.xml"
    baseline = tmp_path / "baseline.json"
    # Baseline = 75%, current = 70% → drop 5% > tolerance 0.5%.
    baseline.write_text(json.dumps({"coverage_percent": 75.0}), encoding="utf-8")
    _write_coverage_xml(cov_xml, 0.70)

    result = _run_gate(
        "--coverage-xml",
        str(cov_xml),
        "--baseline",
        str(baseline),
        "--threshold",
        "50",
        "--strict",
    )
    assert result.returncode == 1
    assert "drop" in result.stderr.lower()
