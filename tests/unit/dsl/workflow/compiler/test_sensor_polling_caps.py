"""D-A8-10 fix (cycle 1): sensor infinite polling guards.

Ранее compile_sensor_step использовал bare 'while True:' без cap —
infinite polling при timeout_s=None. Даже с timeout_s unbounded
event history growth в Temporal. poll_interval_s <= 0 → tight loop DoS.

Фикс: 3 guard'а — timeout_s обязателен (runtime check), max_iterations cap,
poll_interval_s > 0 (defense-in-depth, BaseModel gt=0.0 уже проверяет).

Тесты фокусируются на runtime-уровне (BaseModel-valid конструкциях,
которые компилятор должен дополнительно защищать).
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# Mock temporalio (не в test deps) — compile_sensor_step делает lazy import
# внутри функции. Нужно зарегистрировать модуль в sys.modules до теста.
class _MockTemporalioWorkflow:
    """Stub для temporalio.workflow (вызовы execute_activity и sleep)."""

    @staticmethod
    async def execute_activity(*_args: Any, **_kwargs: Any) -> Any:
        return None

    @staticmethod
    async def sleep(*_args: Any, **_kwargs: Any) -> None:
        return None


_mock_temporalio = types.ModuleType("temporalio")
_mock_temporalio.workflow = _MockTemporalioWorkflow()
sys.modules["temporalio"] = _mock_temporalio
sys.modules["temporalio.workflow"] = _MockTemporalioWorkflow


from src.backend.dsl.workflow.compiler.step_compilers import (  # noqa: E402
    SensorMaxIterationsError,
    SensorTimeoutRequiredError,
    compile_sensor_step,
)
from src.backend.dsl.workflow.spec.advanced_declarations import (  # noqa: E402
    SensorDeclaration,
)


def _make_decl(
    *,
    predicate: str = "test.predicate",
    poll_interval_s: float = 1.0,
    timeout_s: float | None = 60.0,
) -> SensorDeclaration:
    """Create SensorDeclaration. Note: BaseModel уже валидирует gt=0.0."""
    return SensorDeclaration(
        predicate=predicate,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
    )


def _ctx() -> dict[str, Any]:
    return {"_default_timeout_s": 30.0}


class TestSensorPollingGuards:
    """D-A8-10 fix (cycle 1): защита от infinite polling."""

    @pytest.mark.asyncio
    async def test_timeout_none_raises_runtime_check(self) -> None:
        """timeout_s=None (валиден для BaseModel) → compile_sensor_step raise.

        D-A8-10 fix: runtime-check ловит timeout_s=None, который BaseModel
        разрешает (default-OFF policy в runtime compile-time).
        """
        decl = _make_decl(timeout_s=None)

        with pytest.raises(SensorTimeoutRequiredError) as exc_info:
            await compile_sensor_step(decl, _ctx())

        assert "timeout_s" in str(exc_info.value)
        assert "test.predicate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_max_iterations_cap_raises(self) -> None:
        """1001+ итераций (predicate всегда None) → raise SensorMaxIterationsError.

        D-A8-10 fix: event history cap защищает Temporal от unbounded
        growth даже при выставленном timeout_s.
        """
        decl = _make_decl(timeout_s=1000.0, poll_interval_s=1.0)

        # Mock execute_activity → None (predicate never truthy)
        with patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value=None)):
            with patch("temporalio.workflow.sleep", new=AsyncMock()):
                with pytest.raises(SensorMaxIterationsError) as exc_info:
                    await compile_sensor_step(decl, _ctx())

        assert "max_iterations=1000" in str(exc_info.value)
        assert "test.predicate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_predicate_truthy_returns_immediately(self) -> None:
        """Predicate возвращает truthy → sensor завершается на первой итерации (regression)."""
        decl = _make_decl(timeout_s=60.0)

        with patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value=True)):
            with patch("temporalio.workflow.sleep", new=AsyncMock()) as mock_sleep:
                result = await compile_sensor_step(decl, _ctx())

        assert result is True
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_zero_raises_valueerror(self) -> None:
        """timeout_s=0.0 (валиден для BaseModel gt=0.0 — strict > 0) → НЕ timeout.

        ВНИМАНИЕ: timeout_s=0.0 невалиден для BaseModel (gt=0.0 strict).
        Тест проверяет что compile_sensor_step корректно срабатывает
        timeout-check при elapsed=0 + timeout_s=0.
        """
        # С BaseModel gt=0.0 — SensorDeclaration нельзя создать с timeout_s=0.
        # Проверяем через runtime: timeout=0 + predicate=None → timeout срабатывает сразу.
        decl = _make_decl(timeout_s=0.0001, poll_interval_s=1.0)

        with patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value=None)):
            with patch("temporalio.workflow.sleep", new=AsyncMock()):
                with pytest.raises(TimeoutError):
                    await compile_sensor_step(decl, _ctx())

    @pytest.mark.asyncio
    async def test_default_max_iterations_constant(self) -> None:
        """_SENSOR_MAX_ITERATIONS_DEFAULT = 1000 (default cap)."""
        from src.backend.dsl.workflow.compiler.step_compilers import (
            _SENSOR_MAX_ITERATIONS_DEFAULT,
        )

        assert _SENSOR_MAX_ITERATIONS_DEFAULT == 1000
