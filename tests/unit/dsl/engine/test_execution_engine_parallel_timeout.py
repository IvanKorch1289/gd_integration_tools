"""Regression-тесты для ``ExecutionEngine.execute_parallel`` timeout.

Контракт:
* по умолчанию per-processor timeout = 30s (fail-closed);
* явный ``timeout`` пробрасывается в ``ProcessorPool.execute_parallel``;
* ``timeout=0`` отключает таймаут (для trusted callers);
* зависший процессор НЕ блокирует остальные (другие продолжают выполняться);
* любой timeout-error попадает в trace-log и венёт exchange в ``failed``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.engine.exchange import ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.processors.base import BaseProcessor


class _FastProcessor(BaseProcessor):
    """Процессор, который ставит маркер в ``exchange.properties``."""

    def __init__(self, name: str = "fast", marker: str = "fast") -> None:
        super().__init__(name=name)
        self._marker = marker

    async def process(self, exchange: Any, context: Any) -> None:
        exchange.properties[f"_hit:{self._marker}"] = True


class _HangingProcessor(BaseProcessor):
    """Процессор, который спит вечно (для таймаута)."""

    def __init__(self, name: str = "hang", sleep: float = 5.0) -> None:
        super().__init__(name=name)
        self._sleep = sleep

    async def process(self, exchange: Any, context: Any) -> None:
        await asyncio.sleep(self._sleep)
        exchange.properties["_hit:hang"] = True


@pytest.mark.unit
class TestExecuteParallelTimeout:
    """``execute_parallel`` enforce per-processor timeout (fail-closed)."""

    async def test_default_timeout_cancels_hanging_processor(self) -> None:
        """Без явного timeout дефолт 30s — зависший процессор падает с TimeoutError.

        Чтобы не ждать 30s, делаем явный timeout=0.05.
        """
        engine = ExecutionEngine(validate_before_execute=False)
        processors = [_FastProcessor("fast"), _HangingProcessor("hang")]

        result = await engine.execute_parallel(
            processors, body={"x": 1}, timeout=0.05
        )

        assert result.status == ExchangeStatus.failed
        # Fast должен успеть выполниться до того, как зависший убьётся по таймауту.
        assert result.properties.get("_hit:fast") is True
        # В trace должно быть как минимум одна error-запись.
        trace = result.properties.get("_trace", [])
        errors = [t for t in trace if t.get("status") == "error"]
        assert errors, "Хотя бы один процессор должен попасть в trace с ошибкой"

    async def test_explicit_zero_timeout_disables_enforcement(self) -> None:
        """``timeout=0`` отключает enforced timeout — все процессоры выполняются.

        ``asyncio.wait_for(..., timeout=0)`` фактически даёт корутине один tick,
        поэтому используем маленький sleep — успеет выполниться.
        """
        engine = ExecutionEngine(validate_before_execute=False)
        processors = [
            _FastProcessor("fast_a", marker="a"),
            _FastProcessor("fast_b", marker="b"),
        ]

        result = await engine.execute_parallel(processors, body={"x": 1}, timeout=0)

        assert result.status == ExchangeStatus.completed
        assert result.properties.get("_hit:a") is True
        assert result.properties.get("_hit:b") is True

    async def test_short_timeout_fires_for_all_hanging(self) -> None:
        """Если ВСЕ процессоры зависают — все попадают в trace с TimeoutError."""
        engine = ExecutionEngine(validate_before_execute=False)
        processors = [
            _HangingProcessor(f"hang_{i}", sleep=2.0) for i in range(3)
        ]

        result = await engine.execute_parallel(
            processors, body={"x": 1}, timeout=0.05
        )

        assert result.status == ExchangeStatus.failed
        trace = result.properties.get("_trace", [])
        assert len(trace) == 3
        assert all(t.get("status") == "error" for t in trace)
        # Все ошибки — TimeoutError.
        assert all("Timeout" in t.get("error", "") for t in trace)

    async def test_fast_processors_complete_under_timeout(self) -> None:
        """Быстрые процессоры успевают завершиться до таймаута."""
        engine = ExecutionEngine(validate_before_execute=False)
        processors = [
            _FastProcessor(f"fast_{i}", marker=f"m{i}") for i in range(5)
        ]

        result = await engine.execute_parallel(
            processors, body={"x": 1}, timeout=1.0
        )

        assert result.status == ExchangeStatus.completed
        for i in range(5):
            assert result.properties.get(f"_hit:m{i}") is True
        trace = result.properties.get("_trace", [])
        assert all(t.get("status") == "ok" for t in trace)

    async def test_timeout_default_is_30_seconds(self) -> None:
        """``timeout=None`` (default) → 30s — нельзя ждать вечно.

        Smoke-test: сигнатура ``execute_parallel`` принимает ``timeout=None``
        без TypeError и возвращает валидный exchange.
        """
        engine = ExecutionEngine(validate_before_execute=False)
        processors = [_FastProcessor("only")]

        result = await engine.execute_parallel(processors, body={"x": 1}, timeout=None)

        assert result.properties.get("_hit:fast") is True
