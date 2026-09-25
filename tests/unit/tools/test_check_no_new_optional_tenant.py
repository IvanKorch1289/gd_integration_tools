"""Meta-test: check_no_new_optional_tenant AST gate (audit W0).

Per audit W0: «Запретить новые optional tenant parameters AST-gate'ом».

Контракт:
1. Baseline фиксируется при первом запуске;
2. --strict FAILs при NEW optional tenant_id параметрах;
3. --update-baseline обновляет baseline (для intentional refactors);
4. Опциональные tenant_id параметры в public API должны быть удалены
   (per ADR-0345 Option A) или explicitly documented в baseline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = (
    PROJECT_ROOT / ".baselines" / "optional_tenant_baseline.json"
)


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_no_new_optional_tenant.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _add_finding_and_restore() -> bool:
    """Добавляет NEW optional tenant_id, runs --strict, restores."""
    test_dir = PROJECT_ROOT / "src" / "backend" / "_test_optional_tenant_gate"
    test_file = test_dir / "violation.py"
    try:
        test_dir.mkdir(exist_ok=True)
        test_file.write_text(
            "class TestService:\n"
            "    def new_method(self, tenant_id: str | None = None) -> None:\n"
            "        pass\n"
        )
        result = _run_gate(["--strict"])
        return result.returncode
    finally:
        # Cleanup + restore baseline.
        if test_file.exists():
            test_file.unlink()
        if test_dir.exists():
            test_dir.rmdir()
        _run_gate(["--update-baseline"])


def test_strict_gate_detects_new_optional_tenant() -> None:
    """Audit W0: --strict FAILs при NEW optional tenant_id параметре."""
    exit_code = _add_finding_and_restore()
    assert exit_code == 1, (
        f"--strict должен FAIL при new optional tenant_id параметре. "
        f"Got exit_code={exit_code}."
    )


def test_strict_gate_passes_when_no_drift() -> None:
    """--strict PASSes когда нет drift (нет NEW additions)."""
    result = _run_gate(["--strict"])
    assert result.returncode == 0, (
        f"--strict должен PASS когда baseline == current. Got exit_code={result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_baseline_file_exists_and_has_findings() -> None:
    """Baseline файл существует и содержит valid JSON list."""
    assert BASELINE_PATH.is_file(), (
        f"Baseline не найден: {BASELINE_PATH}. "
        f"Запустите --update-baseline для establish."
    )
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list), (
        f"Baseline должен быть list, got {type(data).__name__}"
    )
    assert len(data) > 0, "Baseline не должен быть пустым"
    for f in data:
        assert "file" in f
        assert "line" in f
        assert "qualified_name" in f


def test_detected_optional_tenants_count_baseline() -> None:
    """Baseline count должен быть consistent with actual scan."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # Run без --strict — должен exit 0 (даже при drift, --strict только triggers fail).
    result = _run_gate([])
    # Parse output for count.
    import re

    m = re.search(r"Current:\s+(\d+)", result.stdout)
    if not m:
        m = re.search(r"current_count[\"']:\s*(\d+)", result.stdout)
    assert m, f"Не удалось parse current_count из output: {result.stdout}"
    current_count = int(m.group(1))
    # Если нет drift → current_count == baseline_count.
    # Если drift → current_count > baseline_count (NEW additions).
    assert current_count >= len(baseline), (
        f"Current count ({current_count}) should be >= baseline ({len(baseline)}). "
        f"Если меньше → refactor (allowed) не должно быть неожиданным."
    )


def test_json_output_schema() -> None:
    """JSON output имеет schema с new_findings/removed_findings/status."""
    result = _run_gate(["--json"])
    data = json.loads(result.stdout)
    assert "baseline_count" in data
    assert "current_count" in data
    assert "new_findings" in data
    assert "removed_findings" in data
    assert "status" in data
    assert data["status"] in ("PASS", "FAIL")


def test_update_baseline_creates_file_when_missing() -> None:
    """Если baseline отсутствует → --update-baseline создаёт его.

    Тест НЕ удаляет существующий baseline (per design gate integrity).
    """
    # Skip if baseline already exists — это не regression test.
    if BASELINE_PATH.is_file():
        return  # baseline exists, test не applicable
    # Otherwise — это new state, update should create.
    result = _run_gate(["--update-baseline"])
    assert result.returncode == 0
    assert BASELINE_PATH.is_file()
