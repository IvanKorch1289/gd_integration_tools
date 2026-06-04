"""Тесты Pydantic-деклараций DSL workflow (Sprint 4 §4.3).

Проверяют:
* Round-trip ``dict → Declaration → dict`` для каждого типа шага.
* Discriminator корректно резолвит ``type`` поле.
* Базовые валидации (min_length, gt=0 и пр.).
* WorkflowDeclaration агрегирует список шагов разных типов.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.dsl.workflow import (
    ActivityDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)

# ── ActivityDeclaration ──


def test_activity_minimal() -> None:
    a = ActivityDeclaration(name="orders.create")
    assert a.type == "activity"
    assert a.name == "orders.create"
    assert a.args == {}
    assert a.retry_policy is None


def test_activity_with_retry_policy() -> None:
    a = ActivityDeclaration(
        name="orders.create",
        timeout_s=30.0,
        retry_policy=RetryPolicy(max_attempts=5, initial_interval_s=2.0),
        output_key="order_id",
    )
    assert a.timeout_s == 30.0
    assert a.retry_policy is not None
    assert a.retry_policy.max_attempts == 5
    assert a.output_key == "order_id"


def test_activity_round_trip_json() -> None:
    src = {
        "type": "activity",
        "name": "ai.embed",
        "args": {"text": "hello"},
        "timeout_s": 10.0,
    }
    a = ActivityDeclaration.model_validate(src)
    a2 = ActivityDeclaration.model_validate(a.model_dump())
    assert a == a2
    assert a.name == src["name"]
    assert a.args == src["args"]
    assert a.timeout_s == src["timeout_s"]


def test_activity_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ActivityDeclaration(name="x", unknown_field="y")  # type: ignore[call-arg]


def test_activity_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        ActivityDeclaration(name="")


# ── RetryPolicy ──


def test_retry_policy_defaults() -> None:
    p = RetryPolicy()
    assert p.max_attempts == 3
    assert p.initial_interval_s == 1.0
    assert p.backoff_coefficient == 2.0
    assert p.non_retryable_errors == ()


def test_retry_policy_rejects_bad_max_attempts() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=0)


def test_retry_policy_jitter_default_none() -> None:
    p = RetryPolicy()
    assert p.jitter is None


def test_retry_policy_jitter_value() -> None:
    p = RetryPolicy(jitter=0.5)
    assert p.jitter == 0.5


def test_retry_policy_jitter_validation() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(jitter=-0.1)
    with pytest.raises(ValidationError):
        RetryPolicy(jitter=1.5)


# ── SagaDeclaration ──


def test_saga_with_forward_and_compensate() -> None:
    saga = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="payment.charge"),
            ActivityDeclaration(name="inventory.reserve"),
        ],
        compensate=[
            ActivityDeclaration(name="payment.refund"),
            ActivityDeclaration(name="inventory.release"),
        ],
    )
    assert saga.type == "saga"
    assert len(saga.forward) == 2
    assert len(saga.compensate) == 2


def test_saga_requires_at_least_one_forward() -> None:
    with pytest.raises(ValidationError):
        SagaDeclaration(forward=[], compensate=[])


# ── Signal / Sleep / Sensor ──


def test_signal_wait_minimal() -> None:
    s = SignalWaitDeclaration(signal_name="approve")
    assert s.type == "wait_signal"
    assert s.timeout_s is None


def test_sleep_round_trip() -> None:
    s = SleepDeclaration(duration_s=60.0)
    dump = s.model_dump()
    parsed = SleepDeclaration.model_validate(dump)
    assert parsed == s


def test_sensor_with_custom_interval() -> None:
    s = SensorDeclaration(
        predicate="src.backend.workflows.sensors:is_ready",
        poll_interval_s=15.0,
        timeout_s=600.0,
    )
    assert s.poll_interval_s == 15.0


# ── WorkflowDeclaration (composition) ──


def test_workflow_minimal() -> None:
    wf = WorkflowDeclaration(
        name="credit.assess", steps=[ActivityDeclaration(name="credit.score")]
    )
    assert wf.name == "credit.assess"
    assert len(wf.steps) == 1


def test_workflow_with_mixed_steps_via_discriminator() -> None:
    raw = {
        "name": "order.flow",
        "description": "Полный поток оформления заказа",
        "steps": [
            {"type": "activity", "name": "orders.create"},
            {
                "type": "saga",
                "forward": [{"type": "activity", "name": "payment.charge"}],
                "compensate": [{"type": "activity", "name": "payment.refund"}],
            },
            {"type": "wait_signal", "signal_name": "manager_approve"},
            {"type": "sleep", "duration_s": 5.0},
            {"type": "sensor", "predicate": "fn:is_done", "poll_interval_s": 10.0},
        ],
    }
    wf = WorkflowDeclaration.model_validate(raw)
    assert len(wf.steps) == 5
    assert isinstance(wf.steps[0], ActivityDeclaration)
    assert isinstance(wf.steps[1], SagaDeclaration)
    assert isinstance(wf.steps[2], SignalWaitDeclaration)
    assert isinstance(wf.steps[3], SleepDeclaration)
    assert isinstance(wf.steps[4], SensorDeclaration)


def test_workflow_round_trip() -> None:
    wf = WorkflowDeclaration(
        name="ai.rag",
        steps=[
            ActivityDeclaration(name="ai.retrieve", output_key="docs"),
            ActivityDeclaration(
                name="ai.generate", retry_policy=RetryPolicy(max_attempts=2)
            ),
        ],
        default_timeout_s=120.0,
    )
    dump = wf.model_dump()
    parsed = WorkflowDeclaration.model_validate(dump)
    assert parsed == wf


def test_workflow_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        WorkflowDeclaration(name="x", steps=[])
