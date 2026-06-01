"""Тесты fluent ``WorkflowBuilder`` (Sprint 4 §4.3).

Проверяют:
* Chain-стиль для всех 5 типов шагов (activity/saga/signal/sleep/sensor).
* Делегирование в Pydantic-валидацию через :meth:`build`.
* Round-trip: builder → declaration → ``model_dump()`` → re-validate.
* Саб-builder ``SagaBuilder`` с forward/compensate цепочками.
* Default-значения timeout / retry workflow-уровня.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.dsl.workflow import (
    ActivityDeclaration,
    RetryPolicy,
    SagaBuilder,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowBuilder,
    WorkflowDeclaration,
)


def test_builder_minimal_single_activity() -> None:
    wf = WorkflowBuilder("orders.create").activity("orders.write").build()
    assert isinstance(wf, WorkflowDeclaration)
    assert wf.name == "orders.create"
    assert len(wf.steps) == 1
    assert isinstance(wf.steps[0], ActivityDeclaration)
    assert wf.steps[0].name == "orders.write"


def test_builder_chain_returns_self() -> None:
    builder = WorkflowBuilder("ai.rag")
    same = builder.activity("ai.retrieve").activity("ai.generate")
    assert same is builder
    wf = builder.build()
    assert len(wf.steps) == 2
    assert all(isinstance(s, ActivityDeclaration) for s in wf.steps)


def test_builder_description_and_defaults() -> None:
    policy = RetryPolicy(max_attempts=5, initial_interval_s=2.0)
    wf = (
        WorkflowBuilder("flow")
        .description("Описание процесса")
        .default_timeout(120.0)
        .default_retry(policy)
        .activity("step.one")
        .build()
    )
    assert wf.description == "Описание процесса"
    assert wf.default_timeout_s == 120.0
    assert wf.default_retry_policy == policy


def test_builder_activity_with_full_options() -> None:
    rp = RetryPolicy(max_attempts=4)
    wf = (
        WorkflowBuilder("flow")
        .activity(
            "ai.embed",
            args={"text": "hello"},
            timeout_s=15.0,
            retry_policy=rp,
            output_key="vector",
        )
        .build()
    )
    step = wf.steps[0]
    assert isinstance(step, ActivityDeclaration)
    assert step.args == {"text": "hello"}
    assert step.timeout_s == 15.0
    assert step.retry_policy == rp
    assert step.output_key == "vector"


def test_builder_signal_sleep_sensor() -> None:
    wf = (
        WorkflowBuilder("hitl")
        .wait_for_signal("approve", timeout_s=600.0, output_key="decision")
        .sleep(2.5)
        .sensor("module:is_ready", poll_interval_s=15.0, timeout_s=900.0)
        .build()
    )
    assert isinstance(wf.steps[0], SignalWaitDeclaration)
    assert wf.steps[0].signal_name == "approve"
    assert wf.steps[0].timeout_s == 600.0
    assert wf.steps[0].output_key == "decision"

    assert isinstance(wf.steps[1], SleepDeclaration)
    assert wf.steps[1].duration_s == 2.5

    assert isinstance(wf.steps[2], SensorDeclaration)
    assert wf.steps[2].predicate == "module:is_ready"
    assert wf.steps[2].poll_interval_s == 15.0


def test_builder_saga_round_trip() -> None:
    wf = (
        WorkflowBuilder("payment.flow")
        .saga()
        .forward("payment.charge")
        .forward("inventory.reserve")
        .compensate("payment.refund")
        .compensate("inventory.release")
        .end_saga()
        .build()
    )
    assert len(wf.steps) == 1
    saga = wf.steps[0]
    assert isinstance(saga, SagaDeclaration)
    assert [a.name for a in saga.forward] == ["payment.charge", "inventory.reserve"]
    assert [a.name for a in saga.compensate] == ["payment.refund", "inventory.release"]


def test_builder_saga_returns_subbuilder() -> None:
    saga_b = WorkflowBuilder("flow").saga()
    assert isinstance(saga_b, SagaBuilder)
    chained = saga_b.forward("a").compensate("b")
    assert chained is saga_b


def test_builder_saga_end_returns_parent() -> None:
    wb = WorkflowBuilder("flow")
    parent = wb.saga().forward("a").end_saga()
    assert parent is wb


def test_builder_saga_without_forward_fails_on_end_saga() -> None:
    saga_b = WorkflowBuilder("flow").saga()
    with pytest.raises(ValidationError):
        saga_b.end_saga()


def test_builder_combined_all_step_types() -> None:
    wf = (
        WorkflowBuilder("orchestration")
        .description("Полный путь заявки")
        .activity("intake.parse", output_key="parsed")
        .saga()
        .forward("payment.charge")
        .compensate("payment.refund")
        .end_saga()
        .wait_for_signal("manager_approve")
        .sleep(1.0)
        .sensor("checks:downstream_ready", poll_interval_s=30.0)
        .build()
    )
    assert len(wf.steps) == 5
    assert isinstance(wf.steps[0], ActivityDeclaration)
    assert isinstance(wf.steps[1], SagaDeclaration)
    assert isinstance(wf.steps[2], SignalWaitDeclaration)
    assert isinstance(wf.steps[3], SleepDeclaration)
    assert isinstance(wf.steps[4], SensorDeclaration)


def test_builder_round_trip_via_model_dump() -> None:
    wf1 = (
        WorkflowBuilder("rag.pipeline")
        .activity("ai.retrieve", output_key="docs")
        .activity("ai.rerank", output_key="ranked")
        .activity("ai.generate", retry_policy=RetryPolicy(max_attempts=2))
        .build()
    )
    payload = wf1.model_dump()
    wf2 = WorkflowDeclaration.model_validate(payload)
    assert wf1 == wf2


def test_builder_empty_workflow_fails_on_build() -> None:
    with pytest.raises(ValidationError):
        WorkflowBuilder("empty").build()


def test_builder_rejects_empty_activity_name_on_build() -> None:
    wb = WorkflowBuilder("flow")
    with pytest.raises(ValidationError):
        wb.activity("")


def test_builder_default_timeout_default_value() -> None:
    wf = WorkflowBuilder("flow").activity("a").build()
    assert wf.default_timeout_s == 300.0
    assert wf.default_retry_policy is None


def test_builder_multiple_sagas_in_one_workflow() -> None:
    wf = (
        WorkflowBuilder("multi.saga")
        .saga()
        .forward("step.one")
        .compensate("step.one.rollback")
        .end_saga()
        .activity("between.step")
        .saga()
        .forward("step.two")
        .end_saga()
        .build()
    )
    assert len(wf.steps) == 3
    assert isinstance(wf.steps[0], SagaDeclaration)
    assert isinstance(wf.steps[1], ActivityDeclaration)
    assert isinstance(wf.steps[2], SagaDeclaration)
    assert len(wf.steps[2].compensate) == 0


def test_workflow_builder_pause() -> None:
    """Test that .pause() adds a PauseDeclaration step to the workflow."""
    from src.backend.dsl.workflow.spec import PauseDeclaration

    wf = (
        WorkflowBuilder("credit.flow")
        .activity("credit.fetch_score", output_key="score")
        .pause(output_key="paused_at")
        .activity("credit.approve")
        .build()
    )
    assert len(wf.steps) == 3
    assert isinstance(wf.steps[0], ActivityDeclaration)
    assert isinstance(wf.steps[1], PauseDeclaration)
    assert isinstance(wf.steps[2], ActivityDeclaration)
    pause_step = wf.steps[1]
    assert pause_step.type == "pause"
    assert pause_step.output_key == "paused_at"


def test_workflow_builder_pause_without_output_key() -> None:
    """Test that .pause() works without output_key."""
    from src.backend.dsl.workflow.spec import PauseDeclaration

    wf = WorkflowBuilder("flow").pause().build()
    assert len(wf.steps) == 1
    assert isinstance(wf.steps[0], PauseDeclaration)
    assert wf.steps[0].output_key is None


def test_workflow_builder_resume() -> None:
    """Test that .resume() adds a ResumeDeclaration step to the workflow."""
    from src.backend.dsl.workflow.spec import PauseDeclaration, ResumeDeclaration

    wf = (
        WorkflowBuilder("credit.flow")
        .pause()
        .activity("credit.approve")
        .resume(checkpoint_id="wf_checkpoint_001")
        .build()
    )
    assert len(wf.steps) == 3
    assert isinstance(wf.steps[0], PauseDeclaration)
    assert isinstance(wf.steps[1], ActivityDeclaration)
    assert isinstance(wf.steps[2], ResumeDeclaration)
    resume_step = wf.steps[2]
    assert resume_step.type == "resume"
    assert resume_step.checkpoint_id == "wf_checkpoint_001"


def test_workflow_builder_resume_without_checkpoint_id() -> None:
    """Test that .resume() works without checkpoint_id."""
    from src.backend.dsl.workflow.spec import ResumeDeclaration

    wf = WorkflowBuilder("flow").resume().build()
    assert len(wf.steps) == 1
    assert isinstance(wf.steps[0], ResumeDeclaration)
    assert wf.steps[0].checkpoint_id is None


def test_workflow_builder_pause_resume_chain() -> None:
    """Test that pause and resume can be chained together."""
    from src.backend.dsl.workflow.spec import PauseDeclaration, ResumeDeclaration

    wf = (
        WorkflowBuilder("flow")
        .activity("step.one")
        .pause(output_key="p1")
        .activity("step.two")
        .resume(checkpoint_id="chk_1")
        .activity("step.three")
        .build()
    )
    assert len(wf.steps) == 5
    assert isinstance(wf.steps[0], ActivityDeclaration)
    assert isinstance(wf.steps[1], PauseDeclaration)
    assert wf.steps[1].output_key == "p1"
    assert isinstance(wf.steps[2], ActivityDeclaration)
    assert isinstance(wf.steps[3], ResumeDeclaration)
    assert wf.steps[3].checkpoint_id == "chk_1"
    assert isinstance(wf.steps[4], ActivityDeclaration)
