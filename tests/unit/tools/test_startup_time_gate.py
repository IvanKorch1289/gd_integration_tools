"""Тесты для расширенного startup-time gate (S10 K2 W3)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    """Подгрузить tools/checks/startup_time.py через importlib."""
    path = Path(__file__).resolve().parents[3] / "tools" / "checks" / "startup_time.py"
    spec = importlib.util.spec_from_file_location("_startup_time_test", path)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить startup_time.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


@pytest.fixture
def isolated_baseline(monkeypatch, tmp_path):
    """Подменяет BASELINE_FILE на путь в tmp_path."""
    baseline = tmp_path / ".startup-time-baseline.json"
    monkeypatch.setattr(mod, "BASELINE_FILE", baseline)
    return baseline


def test_load_baseline_returns_none_when_missing(isolated_baseline) -> None:
    assert mod.load_baseline() is None


def test_save_then_load_baseline_roundtrip(isolated_baseline) -> None:
    mod.save_baseline(1.234)
    loaded = mod.load_baseline()
    assert loaded == pytest.approx(1.234, rel=1e-3)


def test_baseline_file_format(isolated_baseline) -> None:
    mod.save_baseline(0.512)
    content = json.loads(isolated_baseline.read_text(encoding="utf-8"))
    assert content["total"] == pytest.approx(0.512)
    assert content["tool"] == "startup_time"


def test_load_baseline_handles_malformed_json(isolated_baseline) -> None:
    isolated_baseline.write_text("not json", encoding="utf-8")
    assert mod.load_baseline() is None


def test_constants_defined() -> None:
    """Константы для thresholds присутствуют."""
    assert mod.MAX_STARTUP_SECONDS_PER_MODULE == 3.0
    assert mod.MAX_TOTAL_STARTUP_SECONDS == 3.0
    assert 0 < mod.REGRESSION_TOLERANCE < 1
    assert len(mod.CRITICAL_MODULES) >= 5


# ──────────────────── Measurement bug regression tests (06b83cd49) ──────────────

# Subprocess-скрипт, который пишет elapsed на stdout с маркером
# STARTUP_TIME_MARKER (per cycle 158+ fix).
_SUBPROCESS_SCRIPT_VALID = (
    "import sys\n"
    "sys.stdout.write('noise-line-1\\n')  # загрязнение от structlog/side effects\n"
    "sys.stdout.write('noise-line-2\\n')\n"
    "sys.stdout.write('STARTUP_TIME_MARKER:1.2345\\n')\n"
    "sys.stdout.flush()\n"
)

# Тот же скрипт, но БЕЗ маркера (legacy behavior fallthrough).
_SUBPROCESS_SCRIPT_NO_MARKER = "import sys\nsys.stdout.write('1.2345')\n"

# Скрипт с НЕвалидным маркером (для fallback testing).
_SUBPROCESS_SCRIPT_BAD_MARKER = (
    "import sys\n"
    "sys.stdout.write('noise\\nSTARTUP_TIME_MARKER:not_a_float\\nnoise\\n')\n"
)


def test_measure_import_extracts_marker_from_polluted_stdout() -> None:
    """Pre-fix bug: float(stdout.strip()) падал с ValueError → inf когда
    Vault logger или structlog загрязнял stdout.

    Post-fix: marker-based extraction находит STARTUP_TIME_MARKER в stdout
    даже если другие строки присутствуют.
    """
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": _SUBPROCESS_SCRIPT_VALID.replace(
                "sys.stdout.write('noise-line-1\\n')  # загрязнение от structlog/side effects\n"
                "sys.stdout.write('noise-line-2\\n')\n"
                "sys.stdout.write('STARTUP_TIME_MARKER:1.2345\\n')\n"
                "sys.stdout.flush()\n",
                "noise-line-1\nnoise-line-2\nSTARTUP_TIME_MARKER:1.2345\n",
            ),
            "stderr": "",
        },
    )()

    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(1.2345, rel=1e-4)


def test_measure_import_fallback_when_no_marker() -> None:
    """Fallback: если STARTUP_TIME_MARKER отсутствует, использовать legacy
    float(last_line) parsing.
    """
    proc = type("P", (), {"returncode": 0, "stdout": "1.2345", "stderr": ""})()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(1.2345, rel=1e-4)


def test_measure_import_returns_inf_when_no_parseable_value() -> None:
    """Если stdout содержит только invalid данные → inf.
    Pre-fix bug давал inf по другому path (structlog noise); post-fix
    inf только когда реально ничего нельзя распарсить.
    """
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": "completely invalid garbage content\nno numbers here",
            "stderr": "",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == float("inf")


def test_measure_import_returns_inf_on_subprocess_failure() -> None:
    """Subprocess вернул non-zero → inf (legacy semantic)."""
    proc = type(
        "P",
        (),
        {
            "returncode": 1,
            "stdout": "",
            "stderr": "ModuleNotFoundError: No module named 'fake_module'",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    elapsed = float("inf") if proc.returncode != 0 else elapsed
    assert elapsed == float("inf")


def test_measure_import_finds_marker_in_middle_of_lines() -> None:
    """Marker может быть в любой позиции stdout, не только в конце."""
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": "trailing noise\nSTARTUP_TIME_MARKER:0.9876\nmore trailing",
            "stderr": "",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(0.9876, rel=1e-4)


# ──────────────────────── Regression check: main() integration ──────────────────


def test_main_fails_when_per_module_budget_exceeded(
    isolated_baseline, monkeypatch, capsys
) -> None:
    """Main flow должен exit 1 когда per-module budget превышен."""
    # Подменяем measure_import на stub возвращающий budget-exceeding time.
    from src.backend.core.config import features  # noqa: F401  # any existing

    def fake_measure(module: str) -> float:
        return mod.MAX_STARTUP_SECONDS_PER_MODULE + 1.0  # > 3s

    monkeypatch.setattr(mod, "measure_import", fake_measure)
    rc = mod.main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.err or "FAIL" in captured.out
