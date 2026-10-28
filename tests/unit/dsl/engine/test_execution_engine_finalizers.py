"""ADR-0368 — ``ExecutionEngine`` обязан выполнять finalizers exchange.

До фикса движок не вызывал :meth:`Exchange.run_finalizers` → browser-контекст
не возвращался в пул, семафор пула исчерпывался навсегда (2→1→0, третий
``acquire`` — TIMEOUT).

Проверяем:
* finalizers выполняются после успешного pipeline;
* finalizers выполняются даже после падения процессора;
* finalizers выполняются в ``execute_parallel``;
* «зависший» finalizer не блокирует движок (таймаут + shield).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from src.backend.dsl.engine import execution_engine as execution_engine_module
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor


class _FinalizerProcessor(BaseProcessor):
    """Регистрирует cleanup-finalizer на exchange."""

    def __init__(self, calls: list[str], *, fail: bool = False) -> None:
        super().__init__(name="finalizer-proc")
        self._calls = calls
        self._fail = fail

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.add_finalizer(lambda: self._calls.append("cleanup"))
        if self._fail:
            raise RuntimeError("processor boom")


@pytest.mark.unit
class TestExecutionEngineFinalizers:
    """Финализаторы exchange — часть контракта движка."""

    async def test_execute_runs_finalizers(self) -> None:
        calls: list[str] = []
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(route_id="rpa.finalizers", processors=[_FinalizerProcessor(calls)])

        exchange = await engine.execute(pipeline)

        assert exchange.status == ExchangeStatus.completed
        assert calls == ["cleanup"], "finalizers не выполнены движком"

    async def test_execute_runs_finalizers_after_processor_failure(self) -> None:
        calls: list[str] = []
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="rpa.finalizers.fail",
            processors=[_FinalizerProcessor(calls, fail=True)],
        )

        exchange = await engine.execute(pipeline)

        assert exchange.status == ExchangeStatus.failed
        assert calls == ["cleanup"], "finalizers не выполнены после падения процессора"

    async def test_execute_parallel_runs_finalizers(self) -> None:
        calls: list[str] = []
        engine = ExecutionEngine(validate_before_execute=False)

        exchange = await engine.execute_parallel([_FinalizerProcessor(calls)], body={})

        assert exchange.status == ExchangeStatus.completed
        assert calls == ["cleanup"], "finalizers не выполнены в execute_parallel"

    async def test_slow_finalizer_does_not_block_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Зависший finalizer не должен держать движок (таймаут + shield)."""
        monkeypatch.setattr(
            execution_engine_module, "_FINALIZER_TIMEOUT_SECONDS", 0.05
        )
        calls: list[str] = []

        async def _slow_finalizer() -> None:
            await asyncio.sleep(0.3)
            calls.append("cleanup")

        class _SlowFinalizerProcessor(BaseProcessor):
            async def process(self, exchange: Exchange[Any], context: Any) -> None:
                exchange.add_finalizer(_slow_finalizer)

        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="rpa.finalizers.slow",
            processors=[_SlowFinalizerProcessor(name="slow")],
        )

        started = time.monotonic()
        exchange = await engine.execute(pipeline)
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, "движок заблокирован зависшим finalizer'ом"
        assert exchange.status == ExchangeStatus.completed
        # shield: finalizer продолжает выполняться после таймаута движка.
        await asyncio.sleep(0.4)
        assert calls == ["cleanup"]
