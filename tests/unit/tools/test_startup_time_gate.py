"""Тесты для расширенного startup-time gate (S10 K2 W3)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    """Подгрузить tools/checks/startup_time.py через importlib."""
    path = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "checks"
        / "startup_time.py"
    )
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
