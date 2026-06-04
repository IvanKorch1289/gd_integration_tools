"""Unit-тесты ``to_mermaid`` — Sprint 12 K5 W1.

Проверяет:
    * linear flow с activities;
    * parallel branches (saga);
    * gateway (wait_signal);
    * mix shapes.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)
from src.backend.dsl.workflow.visualize import to_mermaid


def test_to_mermaid_linear_activities() -> None:
    wf = WorkflowDeclaration(
        name="linear",
        steps=[
            ActivityDeclaration(name="step1"),
            ActivityDeclaration(name="step2"),
            ActivityDeclaration(name="step3"),
        ],
    )
    mermaid = to_mermaid(wf)
    assert mermaid.startswith("graph TD")
    assert "n0[" in mermaid
    assert "n1[" in mermaid
    assert "n2[" in mermaid
    assert "n0 --> n1" in mermaid
    assert "n1 --> n2" in mermaid


def test_to_mermaid_saga_with_compensate() -> None:
    wf = WorkflowDeclaration(
        name="saga_wf",
        steps=[
            SagaDeclaration(
                forward=[
                    ActivityDeclaration(name="reserve"),
                    ActivityDeclaration(name="ship"),
                ],
                compensate=[ActivityDeclaration(name="refund")],
            ),
            ActivityDeclaration(name="notify"),
        ],
    )
    mermaid = to_mermaid(wf)
    assert "saga" in mermaid
    assert "n0 --> n1" in mermaid


def test_to_mermaid_signal_wait_diamond() -> None:
    wf = WorkflowDeclaration(
        name="hitl",
        steps=[
            ActivityDeclaration(name="request"),
            SignalWaitDeclaration(signal_name="approve"),
            ActivityDeclaration(name="finalize"),
        ],
    )
    mermaid = to_mermaid(wf)
    assert '{"' in mermaid


def test_to_mermaid_mix_shapes() -> None:
    wf = WorkflowDeclaration(
        name="mixed",
        steps=[
            ActivityDeclaration(name="start"),
            SleepDeclaration(duration_s=10.0),
            SensorDeclaration(predicate="src.foo:check"),
            ActivityDeclaration(name="end"),
        ],
    )
    mermaid = to_mermaid(wf)
    assert "((" in mermaid
    assert "{{" in mermaid


def test_to_mermaid_with_color_map_for_diff() -> None:
    wf = WorkflowDeclaration(
        name="diff_wf",
        steps=[ActivityDeclaration(name="kept"), ActivityDeclaration(name="changed")],
    )
    color_map = {"activity:changed": "modified"}
    mermaid = to_mermaid(wf, color_map=color_map)
    assert "classDef cls_modified" in mermaid
    assert "class n1 cls_modified" in mermaid
