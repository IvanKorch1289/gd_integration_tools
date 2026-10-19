"""Tests for ``src.backend.core.orchestration.saga``.

R2.2: Saga primitive поверх WorkflowBackend — durable workflow-orchestrated
saga с forward/compensate Activity шагами.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.orchestration import saga as mod
from src.backend.core.orchestration.saga import (
    ActivityFn,
    SagaPrimitive,
    SagaResult,
    SagaStep,
)


async def _dummy_forward(payload: dict[str, Any]) -> dict[str, Any]:
    return {"result": "ok"}


async def _dummy_compensate(payload: dict[str, Any]) -> dict[str, Any]:
    return {"compensated": True}


class TestActivityFn:
    """ActivityFn type alias."""

    def test_callable_annotation(self) -> None:
        # ActivityFn — Callable[[dict], Awaitable[dict]]
        assert ActivityFn is not None

    def test_callable_can_be_used_as_annotation(self) -> None:
        # Декларация async функции с этой аннотацией работает
        async def my_activity(payload: dict[str, Any]) -> dict[str, Any]:
            return payload

        # callable и возвращает awaitable
        assert callable(my_activity)
        import asyncio

        result = asyncio.run(my_activity({"x": 1}))
        assert result == {"x": 1}


class TestSagaStepDefaults:
    """SagaStep Pydantic model defaults."""

    def test_minimal_construction(self) -> None:
        step = SagaStep(name="step1", forward=_dummy_forward)
        assert step.name == "step1"
        assert step.forward is _dummy_forward

    def test_default_compensate_is_none(self) -> None:
        step = SagaStep(name="step1", forward=_dummy_forward)
        assert step.compensate is None

    def test_default_max_attempts(self) -> None:
        step = SagaStep(name="step1", forward=_dummy_forward)
        assert step.max_attempts == 3

    def test_default_idempotency_key_path(self) -> None:
        step = SagaStep(name="step1", forward=_dummy_forward)
        assert step.idempotency_key_path is None


class TestSagaStepExplicit:
    """Явные значения SagaStep."""

    def test_with_compensate(self) -> None:
        step = SagaStep(
            name="step1",
            forward=_dummy_forward,
            compensate=_dummy_compensate,
        )
        assert step.compensate is _dummy_compensate

    def test_custom_max_attempts(self) -> None:
        step = SagaStep(name="step1", forward=_dummy_forward, max_attempts=10)
        assert step.max_attempts == 10

    def test_idempotency_key_path(self) -> None:
        step = SagaStep(
            name="step1",
            forward=_dummy_forward,
            idempotency_key_path="order.id",
        )
        assert step.idempotency_key_path == "order.id"


class TestSagaStepValidation:
    """Pydantic validation."""

    def test_name_min_length_one(self) -> None:
        # min_length=1 → пустая строка недопустима
        with pytest.raises(ValidationError):
            SagaStep(name="", forward=_dummy_forward)

    def test_extra_forbid(self) -> None:
        # extra="forbid" — лишние поля запрещены
        with pytest.raises(ValidationError):
            SagaStep(
                name="step1",
                forward=_dummy_forward,
                unknown_field="foo",  # type: ignore[call-arg]
            )

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            SagaStep()  # type: ignore[call-arg]


class TestSagaResultDefaults:
    """SagaResult frozen Pydantic model defaults."""

    def test_minimal_construction(self) -> None:
        result = SagaResult(success=True)
        assert result.success is True

    def test_default_completed_steps_empty_tuple(self) -> None:
        result = SagaResult(success=True)
        assert result.completed_steps == ()
        assert isinstance(result.completed_steps, tuple)

    def test_default_compensated_steps_empty_tuple(self) -> None:
        result = SagaResult(success=True)
        assert result.compensated_steps == ()

    def test_default_failure_is_none(self) -> None:
        result = SagaResult(success=True)
        assert result.failure is None

    def test_default_output_empty_dict(self) -> None:
        result = SagaResult(success=True)
        assert result.output == {}


class TestSagaResultExplicit:
    """Явные значения SagaResult."""

    def test_failure_result(self) -> None:
        result = SagaResult(
            success=False,
            completed_steps=("step1", "step2"),
            compensated_steps=("step1",),
            failure={"error": "timeout", "code": 504},
        )
        assert result.success is False
        assert result.completed_steps == ("step1", "step2")
        assert result.compensated_steps == ("step1",)
        assert result.failure == {"error": "timeout", "code": 504}

    def test_with_output(self) -> None:
        result = SagaResult(success=True, output={"result": "ok"})
        assert result.output == {"result": "ok"}


class TestSagaResultFrozen:
    """frozen=True — immutable."""

    def test_cannot_modify_after_creation(self) -> None:
        from pydantic import ValidationError

        result = SagaResult(success=True)
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            SagaResult(success=True, unknown_field="foo")  # type: ignore[call-arg]


class TestSagaPrimitiveProtocol:
    """SagaPrimitive — runtime_checkable Protocol."""

    def test_protocol_importable(self) -> None:
        assert SagaPrimitive is not None

    def test_has_run(self) -> None:
        assert hasattr(SagaPrimitive, "run")

    def test_run_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(SagaPrimitive.run)

    def test_runtime_checkable(self) -> None:
        # SagaPrimitive помечен @runtime_checkable

        class _FakeOrchestrator:
            async def run(  # type: ignore[no-untyped-def]
                self,
                *,
                saga_id: str,
                steps: list[SagaStep],
                input: dict[str, Any],
                namespace: str = "default",
            ) -> SagaResult:
                return SagaResult(success=True)

        orch = _FakeOrchestrator()
        assert isinstance(orch, SagaPrimitive)

    def test_dict_is_not_saga_primitive(self) -> None:
        assert not isinstance({}, SagaPrimitive)

    def test_int_is_not_saga_primitive(self) -> None:
        assert not isinstance(42, SagaPrimitive)

    def test_run_signature(self) -> None:
        sig = inspect.signature(SagaPrimitive.run)
        params = list(sig.parameters.keys())
        # self, *, saga_id, steps, input, namespace
        assert "self" in params
        assert "saga_id" in params
        assert "steps" in params
        assert "input" in params
        assert "namespace" in params

    def test_namespace_default_is_default(self) -> None:
        sig = inspect.signature(SagaPrimitive.run)
        assert sig.parameters["namespace"].default == "default"


class TestAllExports:
    """__all__ проверка."""

    def test_exports_three_classes(self) -> None:
        assert "SagaStep" in mod.__all__
        assert "SagaResult" in mod.__all__
        assert "SagaPrimitive" in mod.__all__
        assert len(mod.__all__) == 3


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.core.orchestration import saga as m

        assert m is mod


class TestSagaStepEquality:
    """Pydantic equality."""

    def test_equal_when_same(self) -> None:
        s1 = SagaStep(name="step1", forward=_dummy_forward, max_attempts=3)
        s2 = SagaStep(name="step1", forward=_dummy_forward, max_attempts=3)
        assert s1 == s2

    def test_not_equal_when_name_differs(self) -> None:
        s1 = SagaStep(name="step1", forward=_dummy_forward)
        s2 = SagaStep(name="step2", forward=_dummy_forward)
        assert s1 != s2


class TestSagaResultEquality:
    """Pydantic equality SagaResult."""

    def test_equal_when_same(self) -> None:
        r1 = SagaResult(success=True, output={"x": 1})
        r2 = SagaResult(success=True, output={"x": 1})
        assert r1 == r2

    def test_not_equal_different_success(self) -> None:
        r1 = SagaResult(success=True)
        r2 = SagaResult(success=False)
        assert r1 != r2


class TestSagaStepWithRealCallables:
    """SagaStep с реальными async функциями."""

    def test_works_with_lambda_async(self) -> None:
        async def my_fwd(payload: dict[str, Any]) -> dict[str, Any]:
            return {**payload, "step": "done"}

        step = SagaStep(name="s1", forward=my_fwd)
        assert step.forward is my_fwd

    def test_compensate_optional_in_practice(self) -> None:
        # Saga step может не иметь compensate (односторонняя операция)
        step = SagaStep(name="notify", forward=_dummy_forward)
        assert step.compensate is None


class TestFailureDict:
    """SagaResult.failure — dict с деталями ошибки."""

    def test_failure_can_contain_any_structure(self) -> None:
        # failure — dict[str, Any], структура не фиксирована
        result = SagaResult(
            success=False,
            failure={
                "type": "TimeoutError",
                "message": "Step exceeded 30s",
                "step_index": 2,
                "step_name": "step3",
            },
        )
        assert result.failure["type"] == "TimeoutError"
        assert result.failure["step_index"] == 2

    def test_empty_failure_dict(self) -> None:
        result = SagaResult(success=False, failure={})
        assert result.failure == {}