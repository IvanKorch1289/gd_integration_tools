"""Unit-тесты для ``tools/checks/doctor.py`` (S10 K5 W1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_doctor():
    path = Path(__file__).resolve().parents[3] / "tools" / "checks" / "doctor.py"
    spec = importlib.util.spec_from_file_location("_doctor_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = _load_doctor()


def test_check_result_dataclass_attrs() -> None:
    r = doctor.CheckResult(name="x", ok=True, detail="ok")
    assert r.name == "x" and r.ok is True and r.detail == "ok"


def test_report_all_ok_empty() -> None:
    rep = doctor.DoctorReport()
    assert rep.all_ok is True


def test_report_all_ok_with_failure() -> None:
    rep = doctor.DoctorReport()
    rep.add("a", True)
    rep.add("b", False, "bad")
    assert rep.all_ok is False
    assert len(rep.results) == 2


def test_python_version_passes_for_current_runtime() -> None:
    rep = doctor.DoctorReport()
    doctor.check_python_version(rep)
    assert rep.results[0].ok is True


def test_pyproject_check_finds_project() -> None:
    rep = doctor.DoctorReport()
    doctor.check_pyproject(rep)
    # В корне репозитория pyproject.toml есть и парсится.
    assert rep.results[0].ok is True


def test_taskiq_zero_passes() -> None:
    rep = doctor.DoctorReport()
    doctor.check_taskiq_zero(rep)
    # V15 R-V15-7: запрет taskiq.
    assert rep.results[0].ok is True
    assert "0 taskiq" in rep.results[0].detail


def test_format_report_contains_summary() -> None:
    rep = doctor.DoctorReport()
    rep.add("a", True, "all good")
    rep.add("b", False, "boom")
    out = doctor._format_report(rep)
    assert "Summary: 1/2 OK, 1 FAIL" in out
    assert "[✓] a" in out and "[✗] b" in out
