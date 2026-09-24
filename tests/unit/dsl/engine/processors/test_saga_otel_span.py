"""Contract test: OTEL span-propagation шага саги (v5 P3-12).

Контракт: ``SagaLRA._run_step_with_deadline`` создаёт span ``saga.step``,
который является CHILD текущего span (parent propagation сквозь DSL-шаг).
Tracer изолирован через patch ``opentelemetry.trace.get_tracer`` — глобальный
провайдер не затрагивается.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.saga_lra import SagaLRAProcessor


class _OkStep(BaseProcessor):
    """Шаг-заглушка: успешный process()."""

    def __init__(self) -> None:
        super().__init__(name="ok_step")

    async def process(self, exchange: Any, context: Any) -> None:
        exchange.set_out(body="done")


@pytest.mark.asyncio
async def test_saga_step_span_is_child_of_current_span() -> None:
    """saga.step span создаётся как CHILD текущего span (trace propagation)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.saga")

    proc = SagaLRAProcessor.__new__(SagaLRAProcessor)  # self не нужен в методе
    step = _OkStep()
    exchange = Exchange(in_message=Message(body="x"))
    context = ExecutionContext(route_id="r-1")

    with tracer.start_as_current_span("saga.parent") as parent:
        with patch("opentelemetry.trace.get_tracer", return_value=tracer):
            await proc._run_step_with_deadline(
                step, exchange, context, step_name="reserve_order", kind="action"
            )

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "saga.parent" in names
    assert "saga.step" in names

    child = next(s for s in spans if s.name == "saga.step")
    assert child.parent is not None
    assert child.parent.span_id == parent.get_span_context().span_id
    assert child.attributes["saga.step"] == "reserve_order"
    assert child.attributes["saga.kind"] == "action"


@pytest.mark.asyncio
async def test_no_otel_step_still_runs() -> None:
    """Без OTEL (get_tracer бросает) шаг выполняется — graceful degradation."""
    with patch(
        "opentelemetry.trace.get_tracer", side_effect=RuntimeError("otel disabled")
    ):
        proc = SagaLRAProcessor.__new__(SagaLRAProcessor)
        step = _OkStep()
        exchange = Exchange(in_message=Message(body="x"))
        context = ExecutionContext(route_id="r-1")

        await proc._run_step_with_deadline(
            step, exchange, context, step_name="s1", kind="action"
        )

    assert exchange.status != "failed"
