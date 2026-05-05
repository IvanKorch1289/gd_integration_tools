# ruff: noqa: S101
"""Тесты orchestration primitives Protocol-shape (R2.2)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.orchestration import (
    ApprovalDecision,
    ApprovalRequest,
    DeadlinePolicy,
    DeadlineWithEscalation,
    HumanApproval,
    RetryPolicy,
    RetryWithCompensation,
    SagaPrimitive,
    SagaResult,
    SagaStep,
    Sensor,
    SensorTrigger,
)


async def _noop(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


async def _check_true(payload: dict[str, Any]) -> bool:
    return True


async def _escalate(ctx: dict[str, Any]) -> None:
    return None


class TestSaga:
    def test_step_construct(self) -> None:
        step = SagaStep(name="charge", forward=_noop, compensate=_noop)
        assert step.name == "charge"
        assert step.max_attempts == 3

    def test_step_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SagaStep(name="", forward=_noop)

    def test_result_frozen(self) -> None:
        result = SagaResult(success=True, completed_steps=("charge",))
        with pytest.raises(ValidationError):
            result.success = False


class TestRetry:
    def test_policy_defaults(self) -> None:
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.initial_delay_s == 1.0
        assert policy.multiplier == 2.0

    def test_policy_validation(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=0)

    def test_policy_frozen(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(ValidationError):
            policy.max_attempts = 5


class TestDeadline:
    def test_policy_minimal(self) -> None:
        policy = DeadlinePolicy(deadline=timedelta(minutes=10))
        assert policy.deadline == timedelta(minutes=10)
        assert policy.cancel_on_deadline is True

    def test_policy_with_escalation(self) -> None:
        policy = DeadlinePolicy(
            deadline=timedelta(hours=1),
            escalation_after=timedelta(minutes=55),
            cancel_on_deadline=False,
        )
        assert policy.escalation_after == timedelta(minutes=55)
        assert policy.cancel_on_deadline is False


class TestHumanApproval:
    def test_request_minimal(self) -> None:
        req = ApprovalRequest(request_id="r-1", title="Approve refund")
        assert req.request_id == "r-1"
        assert req.timeout is None

    def test_decision_outcomes(self) -> None:
        d = ApprovalDecision(request_id="r-1", outcome="approved")
        assert d.outcome == "approved"
        with pytest.raises(ValidationError):
            ApprovalDecision(request_id="r-1", outcome="bogus")


class TestSensor:
    def test_trigger_construct(self) -> None:
        trigger = SensorTrigger(
            sensor_id="file-arrived", check=_check_true, poll_interval_s=2.0
        )
        assert trigger.sensor_id == "file-arrived"
        assert trigger.poll_interval_s == 2.0

    def test_trigger_validation(self) -> None:
        with pytest.raises(ValidationError):
            SensorTrigger(sensor_id="", check=_check_true)


class _FakeSaga:
    """Минимальная impl для проверки runtime_checkable."""

    async def run(
        self,
        *,
        saga_id: str,
        steps: list[SagaStep],
        input: dict[str, Any],
        namespace: str = "default",
    ) -> SagaResult:
        return SagaResult(success=True, output=input)


class _FakeRetry:
    async def run(
        self,
        *,
        operation_id: str,
        forward: Any,
        compensate: Any,
        input: dict[str, Any],
        policy: RetryPolicy,
        namespace: str = "default",
    ) -> dict[str, Any]:
        return {"ok": True}


class _FakeDeadline:
    async def run(
        self,
        *,
        operation_id: str,
        forward: Any,
        escalate: Any,
        input: dict[str, Any],
        policy: DeadlinePolicy,
        namespace: str = "default",
    ) -> dict[str, Any]:
        return {"ok": True}


class _FakeApproval:
    async def request(
        self, *, operation_id: str, request: ApprovalRequest, namespace: str = "default"
    ) -> ApprovalDecision:
        return ApprovalDecision(request_id=request.request_id, outcome="approved")


class _FakeSensor:
    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> dict[str, Any]:
        return input


class TestProtocolConformance:
    """runtime_checkable: импл-классы должны проходить isinstance."""

    def test_saga_protocol(self) -> None:
        assert isinstance(_FakeSaga(), SagaPrimitive)

    def test_retry_protocol(self) -> None:
        assert isinstance(_FakeRetry(), RetryWithCompensation)

    def test_deadline_protocol(self) -> None:
        assert isinstance(_FakeDeadline(), DeadlineWithEscalation)

    def test_approval_protocol(self) -> None:
        assert isinstance(_FakeApproval(), HumanApproval)

    def test_sensor_protocol(self) -> None:
        assert isinstance(_FakeSensor(), Sensor)
