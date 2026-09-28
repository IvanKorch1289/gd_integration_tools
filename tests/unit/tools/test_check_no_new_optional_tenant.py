"""Meta-test: check_no_new_optional_tenant AST gate (audit W0).

Per audit W0: «Запретить новые optional tenant parameters AST-gate'ом».

Контракт:
1. Baseline фиксируется при первом запуске;
2. --strict FAILs при NEW optional tenant_id параметрах;
3. --update-baseline обновляет baseline (для intentional refactors);
4. Опциональные tenant_id параметры в public API должны быть удалены
   (per ADR-0345 Option A) или explicitly documented в baseline.

ADR-0350 (identity без номера строки):
5. Перемещение функции внутри файла НЕ является нарушением. Раньше ключом
   был ``(file, line, qualified_name)``, поэтому любой сдвиг кода давал
   ложные NEW + REMOVED, а «починить» гейт можно было только перезаписью
   baseline — то есть замаскировать его. Теперь identity = module +
   qualified name + argument, а перемещение отчётится отдельно как moved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = PROJECT_ROOT / ".baselines" / "optional_tenant_baseline.json"
_GATE = "tools/checks/check_no_new_optional_tenant.py"


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, _GATE, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run_gate_json() -> dict:
    """Запустить gate с --json и распарсить stdout."""
    result = _run_gate(["--json"])
    return json.loads(result.stdout)


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


# ---------------------------------------------------------------------------
# ADR-0350: identity контракта не включает номер строки
# ---------------------------------------------------------------------------

_TMP_GATE_DIR = PROJECT_ROOT / "src" / "backend" / "_test_optional_tenant_gate"


class _TempModule:
    """Создаёт временный модуль в src/ и восстанавливает baseline.

    Используется e2e: gate реально сканирует ``src/backend``, поэтому
    подделать «перемещение» иначе нельзя. Baseline сохраняется побайтово и
    восстанавливается в ``finally`` даже при падении теста.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._path = _TMP_GATE_DIR / f"{name}.py"
        self._backup: bytes | None = None

    def write(self, body: str) -> Path:
        """Создать файл и зафиксировать baseline."""
        self._backup = BASELINE_PATH.read_bytes()
        _TMP_GATE_DIR.mkdir(parents=True, exist_ok=True)
        self._path.write_text(body, encoding="utf-8")
        _run_gate(["--update-baseline"])
        return self._path

    def cleanup(self) -> None:
        """Удалить временный файл и вернуть исходный baseline."""
        if self._path.exists():
            self._path.unlink()
        if _TMP_GATE_DIR.is_dir() and not any(_TMP_GATE_DIR.iterdir()):
            _TMP_GATE_DIR.rmdir()
        if self._backup is not None:
            BASELINE_PATH.write_bytes(self._backup)


_MODULE_BEFORE = (
    "class Service:\n"
    "    def lookup(self, tenant_id: str | None = None) -> int:\n"
    "        return 0\n"
)

# Тот же контракт, сдвинутый на 40 строк вниз. Ничего, кроме позиции, не
# изменилось — именно этот сценарий раньше давал ложные NEW + REMOVED.
_MODULE_AFTER = "# filler\n" * 40 + _MODULE_BEFORE


def test_moving_function_within_file_is_not_reported_as_new() -> None:
    """Перемещение функции = moved, а не NEW (ADR-0350 regression)."""
    mod = _TempModule("moved_check")
    try:
        mod.write(_MODULE_BEFORE)
        mod._path.write_text(_MODULE_AFTER, encoding="utf-8")  # noqa: SLF001

        data = _run_gate_json()
        assert data["new_findings"] == [], (
            f"Перемещение функции не должно давать NEW. Got: {data['new_findings']}"
        )
        assert data["removed_findings"] == [], (
            f"Перемещение не должно давать REMOVED. Got: {data['removed_findings']}"
        )
        assert len(data["moved_findings"]) == 1, (
            f"Ожидался 1 moved. Got: {data['moved_findings']}"
        )
        moved = data["moved_findings"][0]
        assert moved["to_line"] > moved["from_line"], "moved должен показать сдвиг"
        assert data["status"] == "PASS"
    finally:
        mod.cleanup()


def test_moved_function_keeps_strict_exit_zero() -> None:
    """--strict не должен краснеть на перемещении (главный симптом false-green)."""
    mod = _TempModule("moved_strict_check")
    try:
        mod.write(_MODULE_BEFORE)
        mod._path.write_text(_MODULE_AFTER, encoding="utf-8")  # noqa: SLF001

        result = _run_gate(["--strict"])
        assert result.returncode == 0, (
            f"--strict обязан PASS при чистом перемещении. "
            f"exit={result.returncode}\nstdout:\n{result.stdout}"
        )
    finally:
        mod.cleanup()


def test_new_contract_is_reported_as_new_not_moved() -> None:
    """Новый optional tenant_id обязан попасть в new, а не в moved."""
    mod = _TempModule("new_contract_check")
    try:
        mod.write(
            "class Service:\n"
            "    def lookup(self, tenant_id: str | None = None) -> int:\n"
            "        return 0\n"
        )
        mod._path.write_text(
            "class Service:\n"
            "    def lookup(self, tenant_id: str | None = None) -> int:\n"
            "        return 0\n"
            "\n"
            "\n"
            "class BrandNew:\n"
            "    def leaky(self, tenant_id: str | None = None) -> int:\n"
            "        return 0\n",
            encoding="utf-8",
        )

        data = _run_gate_json()
        assert data["status"] == "FAIL", "новый контракт обязан давать FAIL"
        assert len(data["new_findings"]) == 1, (
            f"Ожидался 1 new. Got: {data['new_findings']}"
        )
        assert data["new_findings"][0]["qualified_name"] == "BrandNew.leaky"
        assert not any(
            f["qualified_name"] == "BrandNew.leaky" for f in data["moved_findings"]
        ), "новый контракт не должен попасть в moved"

        result = _run_gate(["--strict"])
        assert result.returncode == 1, (
            f"--strict обязан FAIL при новом optional tenant_id. exit={result.returncode}"
        )
    finally:
        mod.cleanup()


def test_json_schema_separates_moved_changed_and_new() -> None:
    """JSON обязан разделять moved / changed / new (audit W0 fix)."""
    data = _run_gate_json()
    for field in (
        "new_findings",
        "removed_findings",
        "moved_findings",
        "changed_findings",
        "status",
    ):
        assert field in data, f"В JSON отсутствует поле {field!r}"


def test_baseline_entries_use_line_free_identity() -> None:
    """Baseline хранит arg + annotation: identity не зависит от строки."""
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert data, "baseline не должен быть пустым"
    for entry in data:
        assert "file" in entry
        assert "qualified_name" in entry
        assert "arg" in entry, "identity требует имени аргумента"
        assert "annotation" in entry, "baseline хранит аннотацию для changed-детекции"
        # line остаётся, но ТОЛЬКО как информация о перемещении.
        assert "line" in entry


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
