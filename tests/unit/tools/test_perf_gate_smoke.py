"""Smoke-тесты для perf-gate baseline и CLI.

K3 Sprint-2 Wave 4 (S1-T4): подтверждает базовую работоспособность
tests/perf/baseline.json и CLI tools/perf_gate.py без запуска backend.

Sprint 6 K2: добавлены тесты для baseline-режима (--baseline flag) и
feature-flag перехода `perf_gate_strict` warn-only → blocking.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASELINE_PATH = Path("tests/perf/baseline.json")
PERF_GATE_PATH = Path("tools/perf_gate.py")


def test_baseline_json_loadable() -> None:
    """baseline.json загружается как валидный JSON со всеми обязательными полями."""
    assert BASELINE_PATH.exists(), f"baseline.json не найден: {BASELINE_PATH}"

    with BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)

    assert "version" in data, "baseline.json должен содержать поле 'version'"
    assert "endpoints" in data, "baseline.json должен содержать поле 'endpoints'"
    assert isinstance(data["endpoints"], dict), "endpoints должен быть объектом"

    # Каждый эндпойнт должен содержать числовые пороги.
    for endpoint, thresholds in data["endpoints"].items():
        for field in ("p95_ms", "p99_ms", "rps_floor"):
            assert field in thresholds, (
                f"Эндпойнт '{endpoint}' не содержит обязательное поле '{field}'"
            )
            assert isinstance(thresholds[field], (int, float)), (
                f"'{field}' для '{endpoint}' должен быть числом"
            )


def test_perf_gate_module_importable() -> None:
    """tools/perf_gate.py запускается с --help и возвращает код 0."""
    assert PERF_GATE_PATH.exists(), f"perf_gate.py не найден: {PERF_GATE_PATH}"

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(PERF_GATE_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"perf_gate.py --help завершился с кодом {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    # Проверяем, что help содержит ключевые аргументы (Sprint 6 K2: + --baseline + --strict).
    assert "--scenario" in result.stdout, (
        "--scenario должен быть в справке perf_gate.py"
    )
    assert "--baseline" in result.stdout, "S6 K2: --baseline должен быть в справке"
    assert "--strict" in result.stdout, "S6 K2: --strict должен быть в справке"


def test_baseline_has_sprint6_blocks() -> None:
    """Sprint 6 K2: baseline.json содержит profile/sustained, spike, global, ci."""
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)

    assert data.get("version") == "2.0", "S6 K2: ожидаем version=2.0"
    assert "profile" in data, "S6 K2: должен быть блок 'profile'"
    assert "sustained" in data["profile"], "S6 K2: profile.sustained отсутствует"
    assert "spike" in data["profile"], "S6 K2: profile.spike отсутствует"
    assert data["profile"]["sustained"]["rps_target"] == 1000
    assert data["profile"]["spike"]["rps_target"] == 5000
    assert "global" in data, "S6 K2: блок 'global' обязателен"
    assert data["global"]["rps_floor"] == 1000.0
    assert data["global"]["p95_ms"] == 200.0
    assert "ci" in data and data["ci"]["feature_flag"] == "perf_gate_strict"


def _import_perf_gate():
    """Подгрузить tools/perf_gate.py через importlib (для теста)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_perf_gate_test", PERF_GATE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError("Не удалось загрузить perf_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_perf_gate_baseline_thresholds_pure() -> None:
    """Юнит-тест _check_thresholds_baseline без запуска subprocess."""
    perf_gate = _import_perf_gate()

    baseline = {
        "global": {"rps_floor": 1000.0, "p95_ms": 200.0, "error_rate_max": 0.01}
    }

    # Кейс 1: всё в норме.
    passed, viols = perf_gate._check_thresholds_baseline(
        {"rps": 1500.0, "p95_ms": 150.0, "fail_rate": 0.005}, baseline
    )
    assert passed is True, f"должно быть pass, viols={viols}"
    assert viols == []

    # Кейс 2: нарушены все три порога.
    passed, viols = perf_gate._check_thresholds_baseline(
        {"rps": 500.0, "p95_ms": 350.0, "fail_rate": 0.02}, baseline
    )
    assert passed is False
    assert len(viols) == 3, f"ожидалось 3 нарушения, получено: {viols}"
    assert any("RPS" in v for v in viols)
    assert any("p95" in v for v in viols)
    assert any("error_rate" in v for v in viols)


def test_perf_gate_strict_mode_env(monkeypatch) -> None:
    """_is_strict_mode читает ENV FEATURE_PERF_GATE_STRICT."""
    perf_gate = _import_perf_gate()

    # --strict CLI флаг работает.
    args = argparse.Namespace(strict=True)
    assert perf_gate._is_strict_mode(args) is True

    # ENV переменная переопределяет default.
    monkeypatch.setenv("FEATURE_PERF_GATE_STRICT", "true")
    args = argparse.Namespace(strict=False)
    assert perf_gate._is_strict_mode(args) is True

    # Default = False (когда нет CLI и ENV).
    monkeypatch.delenv("FEATURE_PERF_GATE_STRICT", raising=False)
    args = argparse.Namespace(strict=False)
    # Может вернуть True/False в зависимости от feature_flags;
    # главное — не падает.
    result = perf_gate._is_strict_mode(args)
    assert isinstance(result, bool)
