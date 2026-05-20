"""Unit-тесты visualize.py — Sprint 12 K3 W1 + K5 W1.

Проверяет:
    * to_graphviz для линейного / parallel-branch / gateway / saga;
    * to_mermaid для тех же сценариев;
    * compute_step_diff: added/removed/modified/unchanged;
    * color_map для diff применяется корректно;
    * DOT/Mermaid syntax валиден (basic regex проверки).
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)
from src.backend.dsl.workflow.visualize import (
    compute_step_diff,
    to_graphviz,
    to_mermaid,
)


def _linear_workflow(name: str = "wf", version: str = "1.0") -> WorkflowDeclaration:
    return WorkflowDeclaration(
        name=name,
        version=version,
        steps=[
            ActivityDeclaration(name="fetch"),
            ActivityDeclaration(name="process"),
            ActivityDeclaration(name="store"),
        ],
    )


def test_to_graphviz_linear() -> None:
    wf = _linear_workflow()
    dot = to_graphviz(wf)
    assert dot.startswith('digraph "wf" {')
    assert "n0 -> n1" in dot
    assert "n1 -> n2" in dot
    assert "fetch" in dot
    assert "shape=box" in dot
    assert dot.rstrip().endswith("}")


def test_to_graphviz_with_saga_and_wait_signal() -> None:
    wf = WorkflowDeclaration(
        name="saga_wf",
        steps=[
            SagaDeclaration(
                forward=[
                    ActivityDeclaration(name="reserve"),
                    ActivityDeclaration(name="charge"),
                ],
                compensate=[ActivityDeclaration(name="refund")],
            ),
            SignalWaitDeclaration(signal_name="approve"),
            SleepDeclaration(duration_s=30.0),
        ],
    )
    dot = to_graphviz(wf)
    assert "shape=folder" in dot
    assert "shape=diamond" in dot
    assert "shape=oval" in dot


def test_to_graphviz_with_color_map() -> None:
    wf = _linear_workflow()
    color_map = {"activity:fetch": "green", "activity:process": "orange"}
    dot = to_graphviz(wf, color_map=color_map)
    assert "color=green" in dot
    assert "color=orange" in dot


def test_to_mermaid_linear() -> None:
    wf = _linear_workflow()
    mermaid = to_mermaid(wf)
    assert mermaid.startswith("graph TD")
    assert "n0[" in mermaid
    assert "n0 --> n1" in mermaid
    assert "fetch" in mermaid


def test_to_mermaid_with_special_shapes() -> None:
    wf = WorkflowDeclaration(
        name="mixed",
        steps=[
            ActivityDeclaration(name="start"),
            SignalWaitDeclaration(signal_name="confirm"),
            SleepDeclaration(duration_s=5.0),
        ],
    )
    mermaid = to_mermaid(wf)
    assert "{\"" in mermaid  # wait_signal — ромб
    assert "((" in mermaid  # sleep — круг


def test_compute_step_diff_added_removed_modified() -> None:
    decl_a = WorkflowDeclaration(
        name="wf",
        version="1.0",
        steps=[
            ActivityDeclaration(name="step1"),
            ActivityDeclaration(name="step2", timeout_s=10.0),
            ActivityDeclaration(name="step3"),
        ],
    )
    decl_b = WorkflowDeclaration(
        name="wf",
        version="1.1",
        steps=[
            ActivityDeclaration(name="step1"),
            ActivityDeclaration(name="step2", timeout_s=30.0),  # modified
            ActivityDeclaration(name="step4"),  # added
        ],
    )
    diff_results, color_a, color_b = compute_step_diff(decl_a, decl_b)
    statuses = {r.identity: r.status for r in diff_results}
    assert statuses["activity:step1"] == "unchanged"
    assert statuses["activity:step2"] == "modified"
    assert statuses["activity:step3"] == "removed"
    assert statuses["activity:step4"] == "added"

    assert color_a["activity:step3"] == "red"
    assert color_b["activity:step4"] == "green"
    assert color_a["activity:step2"] == "orange"
    assert color_b["activity:step2"] == "orange"


def test_compute_step_diff_no_changes() -> None:
    wf = _linear_workflow()
    diff_results, color_a, color_b = compute_step_diff(wf, wf)
    assert all(r.status == "unchanged" for r in diff_results)
    assert color_a == {}
    assert color_b == {}


def test_to_mermaid_with_color_map_emits_classdefs() -> None:
    wf = _linear_workflow()
    color_map = {"activity:fetch": "added", "activity:process": "modified"}
    mermaid = to_mermaid(wf, color_map=color_map)
    assert "classDef cls_added" in mermaid
    assert "classDef cls_modified" in mermaid
    assert "class n0 cls_added" in mermaid


def test_visualize_round_trip_with_yaml_diff() -> None:
    """visualize.compute_step_diff и yaml_io.diff согласованы."""
    from src.backend.dsl.workflow.yaml_io import diff as yaml_diff

    decl_a = WorkflowDeclaration(
        name="wf",
        version="1.0",
        steps=[
            ActivityDeclaration(name="a"),
            ActivityDeclaration(name="b"),
        ],
    )
    decl_b = WorkflowDeclaration(
        name="wf",
        version="2.0",
        steps=[
            ActivityDeclaration(name="a"),
            ActivityDeclaration(name="c"),
        ],
    )
    yaml_d = yaml_diff(decl_a, decl_b)
    vis_results, _, _ = compute_step_diff(decl_a, decl_b)
    statuses = {r.identity: r.status for r in vis_results}

    for ident in yaml_d.added_steps:
        assert statuses[ident] == "added"
    for ident in yaml_d.removed_steps:
        assert statuses[ident] == "removed"
