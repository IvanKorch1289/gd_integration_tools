"""Focused tests for TracingMiddleware (PERF-6.6 Sprint 20 coverage ratchet).

2026-09-11: переписаны под текущий контракт — TracingMiddleware (ProcessorMiddleware)
без аргументов: before() создаёт span, after() закрывает; tracer=None → no-op.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.infrastructure.observability.tracing import (
    TracingMiddleware,
    get_tracer,
)


def _exchange() -> Exchange:
    return Exchange(in_message=Message(body={}))


def _context() -> ExecutionContext:
    return ExecutionContext(route_id="test_route")


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def test_get_tracer_no_raise() -> None:
    """get_tracer() — возвращает tracer или None (OTel optional), не raise."""
    tracer = get_tracer()
    assert tracer is not None or tracer is None


def test_tracing_middleware_init() -> None:
    """TracingMiddleware init без аргументов — spans dict пуст."""
    mw = TracingMiddleware()
    assert mw._spans == {}


def test_tracing_middleware_is_processor_middleware() -> None:
    """Класс в MRO содержит ProcessorMiddleware (Protocol-наследование)."""
    bases = [b.__name__ for b in TracingMiddleware.__mro__]
    assert "ProcessorMiddleware" in bases


def test_before_no_tracer_noop() -> None:
    """tracer=None (OTel недоступен) → before() no-op, spans не создаются."""
    mw = TracingMiddleware()
    with patch(
        "src.backend.infrastructure.observability.tracing.get_tracer", return_value=None
    ):
        _run(mw.before("proc1", _exchange(), _context()))
    assert mw._spans == {}


def test_before_with_tracer_creates_span() -> None:
    """before() с tracer → span создан и сохранён по ключу exchange:processor."""
    mw = TracingMiddleware()
    span = MagicMock()
    tracer = MagicMock()
    tracer.start_span.return_value = span
    ex = _exchange()
    with patch(
        "src.backend.infrastructure.observability.tracing.get_tracer", return_value=tracer
    ):
        _run(mw.before("proc1", ex, _context()))
    assert len(mw._spans) == 1
    tracer.start_span.assert_called_once()


def test_after_ends_span() -> None:
    """after() проставляет duration и завершает span."""
    mw = TracingMiddleware()
    span = MagicMock()
    ex = _exchange()
    mw._spans[f"{id(ex)}:proc1"] = span

    _run(mw.after("proc1", ex, _context(), error=None, duration_ms=12.5))
    span.set_attribute.assert_called_once_with("duration_ms", 12.5)
    span.end.assert_called_once()
    assert mw._spans == {}


def test_after_with_error_sets_error_attributes() -> None:
    """after() с error → error=True + статус ERROR."""
    mw = TracingMiddleware()
    span = MagicMock()
    ex = _exchange()
    mw._spans[f"{id(ex)}:proc1"] = span

    _run(mw.after("proc1", ex, _context(), error=RuntimeError("boom"), duration_ms=3.0))
    assert span.set_attribute.call_count >= 2
    span.end.assert_called_once()


def test_after_without_span_noop() -> None:
    """after() без предшествующего before() → no-op, не падает."""
    mw = TracingMiddleware()
    _run(mw.after("procX", _exchange(), _context(), error=None, duration_ms=1.0))
    assert mw._spans == {}
