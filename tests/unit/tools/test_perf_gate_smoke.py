"""Smoke-тесты для perf-gate baseline и CLI.

K3 Sprint-2 Wave 4 (S1-T4): подтверждает базовую работоспособность
tests/perf/baseline.json и CLI tools/perf_gate.py без запуска backend.
"""

from __future__ import annotations

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

    result = subprocess.run(
        [sys.executable, str(PERF_GATE_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"perf_gate.py --help завершился с кодом {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    # Проверяем, что help содержит ключевые аргументы.
    assert "--scenario" in result.stdout, (
        "--scenario должен быть в справке perf_gate.py"
    )
