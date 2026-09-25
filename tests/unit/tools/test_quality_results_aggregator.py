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

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_aggregator(args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "tools/checks/quality_results_aggregator.py",
    ]
    if args:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_aggregator_produces_machine_readable_json() -> None:
    """Aggregator writes ``.audit/quality-results.json`` per audit W3 spec."""
    result = _run_aggregator()
    assert result.returncode in (0, 1), (
        f"Aggregator должен exit 0 (все PASS) или 1 (есть FAIL). "
        f"Got {result.returncode}. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    output_path = PROJECT_ROOT / ".audit" / "quality-results.json"
    assert output_path.is_file(), (
        f"quality-results.json не создан: {output_path}"
    )
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "audit" in data
    assert "head" in data
    assert "overall_status" in data
    assert "status_counts" in data
    assert "gate_count" in data
    assert "gates" in data
    assert isinstance(data["gates"], list)


def test_aggregator_gate_records_have_audit_w3_schema() -> None:
    """Каждый gate record имеет command, exit_code, duration, head, status,
    counts, artifact_hash, timestamp."""
    result = _run_aggregator()
    data = json.loads((PROJECT_ROOT / ".audit" / "quality-results.json").read_text())
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


def test_aggregator_counts_parsed_from_output() -> None:
    """Counts (user-data, missing tenant filter, etc.) parsed из output."""
    result = _run_aggregator()
    data = json.loads((PROJECT_ROOT / ".audit" / "quality-results.json").read_text())
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


def test_aggregator_status_counts_aggregate() -> None:
    """status_counts содержит aggregate per status."""
    result = _run_aggregator()
    data = json.loads((PROJECT_ROOT / ".audit" / "quality-results.json").read_text())
    total = sum(data["status_counts"].values())
    assert total == data["gate_count"]
    assert total == len(data["gates"])


def test_aggregator_overall_status_logic() -> None:
    """overall_status = PASS если все gates PASS (или NOT_APPLICABLE)."""
    result = _run_aggregator()
    data = json.loads((PROJECT_ROOT / ".audit" / "quality-results.json").read_text())
    statuses = {g["status"] for g in data["gates"]}
    expected_overall = "PASS" if statuses.issubset({"PASS", "NOT_APPLICABLE"}) else "FAIL"
    assert data["overall_status"] == expected_overall, (
        f"overall_status mismatch: got {data['overall_status']}, "
        f"expected {expected_overall}. statuses: {statuses}"
    )


def test_aggregator_command_uses_venv_python() -> None:
    """Aggregator использует .venv/bin/python для stability (full deps).

    Audit W3: «Неполное окружение означает UNKNOWN, а не PASS или FAIL».
    Aggregator должен detect venv python чтобы avoid spurious ENV_FAILURE
    когда системный python3.14 не имеет project deps.
    """
    result = _run_aggregator()
    data = json.loads((PROJECT_ROOT / ".audit" / "quality-results.json").read_text())
    venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    for g in data["gates"]:
        cmd = g["command"]
        # Команда содержит .venv/bin/python path или python3.14 fallback.
        assert (
            venv_python in cmd
            or "python3.14" in cmd
        ), f"Unexpected python interpreter: {cmd}"
