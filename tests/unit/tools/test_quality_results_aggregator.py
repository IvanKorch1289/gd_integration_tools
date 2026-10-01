"""Meta-test: quality_results_aggregator (audit W3 machine-readable format).

Per audit W3 spec: «Нужен machine-readable quality-results.json, который
агрегирует command, exit, duration, tool version, HEAD, counts и
artifact hashes».

Контракт:
1. Aggregator runs all structural gates;
2. Каждый gate имеет status: PASS / FAIL / TOOL_FAILURE / ENV_FAILURE / NOT_APPLICABLE;
3. Output JSON включает command, exit_code, duration_seconds, head,
   tool_version, counts, artifact_hash, timestamp;
4. overall_status = PASS если все gates PASS/NOT_APPLICABLE, иначе FAIL.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Модульная фикстура ниже оборачивает subprocess, которому самому выдан
# ``timeout=600``. Глобальный ``--timeout=120`` (см. Makefile UNIT_TEST_TIMEOUT)
# убивал её на 120-й секунде: замер в простое — 102 с, запас 15%, а под
# нагрузкой (unit-tests идёт с двумя xdist-воркерами) лимит превышается
# стабильно. Симптом — 6 «ERROR at setup … Failed: Timeout (>120.0s)».
# Лимит модуля обязан быть не меньше бюджета оборачиваемого subprocess;
# глобальные 120 с при этом не ослабляются и продолжают ловить зависания.
pytestmark = pytest.mark.timeout(660)


@pytest.fixture(scope="module")
def aggregator_result() -> dict[str, Any]:
    """Один прогон aggregator на весь модуль.

    Aggregator выполняет ~10 gates и занимает ~95 секунд. Раньше КАЖДЫЙ
    тест модуля запускал его заново, из-за чего 6 тестов занимали ~10 минут
    и не укладывались в разумный лимит. Результат детерминирован в рамках
    одного прогона, поэтому одного запуска достаточно.

    Exit code проверяется здесь же: иначе тесты читали бы STALE
    ``quality-results.json`` от предыдущего прогона и проходили бы
    при упавшем aggregator — ровно тот false-green, который audit W3 запрещает.

    F-Y (аудит 2026-10-01): aggregator пишет в TRACKED-файл
    ``.audit/quality-results.json`` абсолютным путём от ``PROJECT_ROOT``.
    Из-за этого прогон тестов портил репозиторий: в коммите оказывались
    чужой ``head``, чужие пути venv и чужие счётчики гейтов. Здесь файл
    снимается побайтово до запуска и восстанавливается в ``finally`` —
    тест получает реальный вывод aggregator'а, но репозиторий не меняется.
    """
    output_path = PROJECT_ROOT / ".audit" / "quality-results.json"
    tracked_snapshot: bytes | None = None
    if output_path.is_file():
        tracked_snapshot = output_path.read_bytes()
    try:
        cmd = [sys.executable, "tools/checks/quality_results_aggregator.py"]
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=600
        )
        assert result.returncode in (0, 1), (
            f"Aggregator должен exit 0 (все PASS) или 1 (есть FAIL). "
            f"Got {result.returncode}. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert output_path.is_file(), f"quality-results.json не создан: {output_path}"
        data: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        return data
    finally:
        # Восстанавливаем tracked-файл: тест не имеет права оставлять
        # в репозитории артефакт своего прогона.
        if tracked_snapshot is not None:
            output_path.write_bytes(tracked_snapshot)
        elif output_path.exists():
            output_path.unlink()


def test_aggregator_produces_machine_readable_json(
    aggregator_result: dict[str, Any],
) -> None:
    """Aggregator writes ``.audit/quality-results.json`` per audit W3 spec."""
    data = aggregator_result
    assert "audit" in data
    assert "head" in data
    assert "overall_status" in data
    assert "status_counts" in data
    assert "gate_count" in data
    assert "gates" in data
    assert isinstance(data["gates"], list)


def test_aggregator_gate_records_have_audit_w3_schema(
    aggregator_result: dict[str, Any],
) -> None:
    """Каждый gate record имеет command, exit_code, duration, head, status,
    counts, artifact_hash, timestamp."""
    data = aggregator_result
    audit_statuses = {"PASS", "FAIL", "TOOL_FAILURE", "ENV_FAILURE", "NOT_APPLICABLE"}
    for g in data["gates"]:
        assert "gate" in g
        assert "command" in g
        assert "exit_code" in g
        assert "duration_seconds" in g
        assert "head" in g
        assert "status" in g
        assert g["status"] in audit_statuses, (
            f"Gate {g['gate']} status={g['status']!r} НЕ в {audit_statuses}. "
            f"Per audit W3: каждый gate должен возвращать один из этих статусов."
        )
        assert "counts" in g
        assert "timestamp" in g
        # artifact_hash может быть None если tool failure без output.
        if g["artifact_hash"] is not None:
            assert g["artifact_hash"].startswith("sha256:")


def test_aggregator_counts_parsed_from_output(
    aggregator_result: dict[str, Any],
) -> None:
    """Counts (user-data, missing tenant filter, etc.) parsed из output."""
    data = aggregator_result
    # classifier_object_authorization должен report unknown_callsites и user_data_callsites.
    classifier_gate = next(
        g for g in data["gates"] if g["gate"] == "classify_object_authorization"
    )
    assert "unknown_callsites" in classifier_gate["counts"], (
        f"classifier gate должен parse unknown_callsites count. Got: "
        f"{classifier_gate['counts']}"
    )
    assert classifier_gate["counts"]["unknown_callsites"] == 0, (
        f"После W0 fix должно быть 0 unknown. Got: "
        f"{classifier_gate['counts']['unknown_callsites']}"
    )


def test_aggregator_status_counts_aggregate(aggregator_result: dict[str, Any]) -> None:
    """status_counts содержит aggregate per status."""
    data = aggregator_result
    total = sum(data["status_counts"].values())
    assert total == data["gate_count"]
    assert total == len(data["gates"])


def test_aggregator_overall_status_logic(aggregator_result: dict[str, Any]) -> None:
    """overall_status = PASS если все gates PASS (или NOT_APPLICABLE)."""
    data = aggregator_result
    statuses = {g["status"] for g in data["gates"]}
    expected_overall = (
        "PASS" if statuses.issubset({"PASS", "NOT_APPLICABLE"}) else "FAIL"
    )
    assert data["overall_status"] == expected_overall, (
        f"overall_status mismatch: got {data['overall_status']}, "
        f"expected {expected_overall}. statuses: {statuses}"
    )


def test_aggregator_command_uses_venv_python(aggregator_result: dict[str, Any]) -> None:
    """Aggregator использует .venv/bin/python для stability (full deps).

    Audit W3: «Неполное окружение означает UNKNOWN, а не PASS или FAIL».
    Aggregator должен detect venv python чтобы avoid spurious ENV_FAILURE
    когда системный python3.14 не имеет project deps.

    Проверяются ТОЛЬКО gates, чья команда запускает python-интерпретатор.
    Standalone-бинари (ruff, mypy) вызываются напрямую и не должны
    подменяться на venv python — прежняя версия теста требовала python
    в каждой команде и падала на ruff-гейтах.
    """
    data = aggregator_result
    venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    python_gates = 0
    for g in data["gates"]:
        # command хранится в JSON как строка (" ".join(...)).
        cmd = g["command"]
        exe = cmd.split()[0] if cmd.split() else ""
        is_python = Path(exe).name.startswith("python") or exe == "python3.14"
        if not is_python:
            continue
        python_gates += 1
        assert venv_python in cmd or "python3.14" in cmd, (
            f"Unexpected python interpreter: {cmd}"
        )
    assert python_gates > 0, (
        f"Не найдено ни одного python-гейта (проверено {len(data['gates'])} gate'ов) — "
        f"тест невалиден"
    )
