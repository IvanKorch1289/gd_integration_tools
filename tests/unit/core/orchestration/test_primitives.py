# ruff: noqa: S101
"""Тесты orchestration primitives Protocol-shape (R2.2).

Примечание: DeadlinePolicy, HumanApproval, RetryWithCompensation и связанные
классы удалены. Оставлены только живые primitive-тесты (Saga, Sensor).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.orchestration import (
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

    def test_sensor_protocol(self) -> None:
        assert isinstance(_FakeSensor(), Sensor)
