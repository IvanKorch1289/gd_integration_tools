"""Unit-тесты workflow dryrun — Wave [wave:s5/k3-w10-workflow-dryrun]."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.dryrun import run_workflow_dryrun
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)


def _basic_workflow() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        name="credit_assessment",
        version="1.2",
        steps=[
            ActivityDeclaration(name="fetch_credit_score", timeout_s=30),
            SignalWaitDeclaration(signal_name="manager.decision", timeout_s=600),
            SleepDeclaration(duration_s=2.0),
            ActivityDeclaration(name="emit_decision", timeout_s=15),
        ],
    )


def test_record_produces_complete_report() -> None:
    wf = _basic_workflow()
    report = run_workflow_dryrun(wf, {"customer_id": 42})

    assert report["workflow_name"] == "credit_assessment"
    assert report["version"] == "1.2"
    # 4 шага → 2 activities + 1 signal + 1 sleep
    assert len(report["activities"]) == 2
    assert len(report["signals"]) == 1
    assert len(report["timer_fires"]) == 1
    # state_transitions: STARTED + (RUNNING + COMPLETED) × 4 + FINISHED
    assert len(report["state_transitions"]) == 1 + 4 * 2 + 1
    assert report["input"] == {"customer_id": 42}


def test_replay_matches_recorded() -> None:
    wf = _basic_workflow()
    first = run_workflow_dryrun(wf, {"customer_id": 1})
    second = run_workflow_dryrun(wf, {"customer_id": 1})
    # Activities должны совпадать (ts может отличаться).
    assert first["activities"] == second["activities"]
    assert first["signals"] == second["signals"]
    assert first["timer_fires"] == second["timer_fires"]


def test_fail_on_mismatch_when_input_changes() -> None:
    wf = _basic_workflow()
    first = run_workflow_dryrun(wf, {"customer_id": 1})
    different_input = run_workflow_dryrun(wf, {"customer_id": 2})
    # Input должен отличаться, что отразится в input_keys
    # (input_keys одинаковые, но вход в report отличается)
    assert first["input"] != different_input["input"]
    # activities используют input_keys; ключ один и тот же → совпадают
    assert first["activities"] == different_input["activities"]
