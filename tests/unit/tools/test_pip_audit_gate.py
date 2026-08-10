"""Regression-тесты для tools/pip_audit_gate.py (D-AUDIT-11-1 fix, cycle 1).

Гейт должен FAIL-CLOSED на:
- несуществующий файл (exit 1);
- malformed JSON (exit 1, не traceback);
- пустой JSON {} (exit 1);
- пустой dependencies [] (exit 1);
- non-empty dependencies без vulns (exit 0).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_GATE = _ROOT / "tools" / "pip_audit_gate.py"


@pytest.fixture
def cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change to tmp_path с pre-existing pip-audit.json (создаётся в тестах по необходимости)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_gate(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run pip_audit_gate.py из cwd; возвращает CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(_GATE)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=15,
    )


def test_missing_file_exits_nonzero(cwd: Path) -> None:
    """pip-audit.json не существует → exit 1, НЕ traceback."""
    result = _run_gate(cwd)
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_malformed_json_exits_nonzero(cwd: Path) -> None:
    """pip-audit.json = garbage → exit 1, понятное сообщение."""
    (cwd / "pip-audit.json").write_text("{not valid json")
    result = _run_gate(cwd)
    assert result.returncode == 1
    assert "malformed" in result.stderr or "JSON" in result.stderr


def test_empty_dependencies_exits_nonzero(cwd: Path) -> None:
    """D-AUDIT-11-1 fix: {"dependencies": []} → exit 1 (fail-CLOSED, было PASS)."""
    (cwd / "pip-audit.json").write_text(json.dumps({"dependencies": []}))
    result = _run_gate(cwd)
    assert result.returncode == 1
    assert "FAIL-CLOSED" in result.stderr or "empty" in result.stderr.lower()


def test_empty_dict_exits_nonzero(cwd: Path) -> None:
    """D-AUDIT-11-1 fix: {} → exit 1 (нет dependencies key)."""
    (cwd / "pip-audit.json").write_text(json.dumps({}))
    result = _run_gate(cwd)
    assert result.returncode == 1


def test_clean_report_exits_zero(cwd: Path) -> None:
    """Real report без vulns → exit 0, PASS."""
    report = {
        "dependencies": [
            {"name": "fastapi", "version": "0.110.0", "vulns": []},
        ],
    }
    (cwd / "pip-audit.json").write_text(json.dumps(report))
    result = _run_gate(cwd)
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_unignored_vuln_exits_nonzero(cwd: Path) -> None:
    """Real report с non-ignored vuln → exit 1, FAIL."""
    report = {
        "dependencies": [
            {
                "name": "fastapi",
                "version": "0.50.0",
                "vulns": [
                    {"id": "GHSA-test-001", "fix_versions": ["0.110.0"]},
                ],
            },
        ],
    }
    (cwd / "pip-audit.json").write_text(json.dumps(report))
    result = _run_gate(cwd)
    assert result.returncode == 1
    assert "GHSA-test-001" in result.stdout
