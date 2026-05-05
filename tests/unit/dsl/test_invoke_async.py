# ruff: noqa: S101
"""Тесты `InvokeAsyncProcessor` (R2.7)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.core.interfaces.action_dispatcher import (
    ActionError,
    ActionResult,
    DispatchContext,
)
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.invoke_async import InvokeAsyncProcessor


class _RecordingDispatcher:
    """Ловушка вызовов dispatcher для тестов."""

    def __init__(self, *, succeed: bool = True, exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], DispatchContext]] = []
        self._succeed = succeed
        self._exc = exc
        self._dispatched = asyncio.Event()

    async def dispatch(
        self, action: str, payload: Any, context: DispatchContext
    ) -> ActionResult:
        self.calls.append((action, dict(payload), context))
        if self._exc is not None:
            self._dispatched.set()
            raise self._exc
        result = (
            ActionResult(success=True, data={"ok": True})
            if self._succeed
            else ActionResult(
                success=False, error=ActionError(code="boom", message="failed")
            )
        )
        self._dispatched.set()
        return result

    def get_metadata(self, action: str) -> Any:  # pragma: no cover
        return None

    def list_actions(self, transport: str | None = None) -> tuple[str, ...]:
        return ()  # pragma: no cover

    def list_metadata(self, transport: str | None = None) -> tuple[Any, ...]:
        return ()  # pragma: no cover

    def register_middleware(self, middleware: Any) -> None:
        pass  # pragma: no cover

    async def wait_dispatched(self, timeout: float = 1.0) -> None:
        await asyncio.wait_for(self._dispatched.wait(), timeout=timeout)


def _make_exchange(body: Any, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
class TestInvokeAsyncBasic:
    async def test_returns_immediately_and_dispatches_in_background(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="orders.notify",
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        exchange = _make_exchange({"order_id": 42})
        exchange.meta.correlation_id = "corr-1"

        await processor.process(exchange, ExecutionContext())

        # process() вернулся мгновенно — но task должен быть создан.
        await dispatcher.wait_dispatched()
        assert len(dispatcher.calls) == 1
        action, payload, ctx = dispatcher.calls[0]
        assert action == "orders.notify"
        assert payload == {"order_id": 42}
        assert ctx.correlation_id == "corr-1"
        assert ctx.source == "dsl_invoke_async"

    async def test_payload_from_properties(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
            payload_path="properties.outbox",
        )
        exchange = _make_exchange(b"raw")
        exchange.properties["outbox"] = {"event": "order_created"}

        await processor.process(exchange, ExecutionContext())
        await dispatcher.wait_dispatched()

        _, payload, _ = dispatcher.calls[0]
        assert payload == {"event": "order_created"}

    async def test_payload_from_headers_wraps_scalar(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
            payload_path="headers.X-Audit-Tag",
        )
        exchange = _make_exchange(None, headers={"X-Audit-Tag": "shipped"})

        await processor.process(exchange, ExecutionContext())
        await dispatcher.wait_dispatched()

        _, payload, _ = dispatcher.calls[0]
        assert payload == {"value": "shipped"}

    async def test_idempotency_key_from_header(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
            idempotency_key_path="headers.X-Idempotency-Key",
        )
        exchange = _make_exchange({"k": "v"}, headers={"X-Idempotency-Key": "abc-123"})

        await processor.process(exchange, ExecutionContext())
        await dispatcher.wait_dispatched()

        _, _, ctx = dispatcher.calls[0]
        assert ctx.idempotency_key == "abc-123"

    async def test_invalid_payload_path_raises(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
            payload_path="bogus",
        )
        exchange = _make_exchange({"x": 1})
        with pytest.raises(ValueError, match="unsupported payload_path"):
            await processor.process(exchange, ExecutionContext())


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_dispatcher_failure_swallowed(self) -> None:
        dispatcher = _RecordingDispatcher(succeed=False)
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        exchange = _make_exchange({"k": 1})

        # Не должен проброситься exc.
        await processor.process(exchange, ExecutionContext())
        await dispatcher.wait_dispatched()
        # Дать background-task завершиться.
        await asyncio.sleep(0)

    async def test_dispatcher_exception_swallowed(self) -> None:
        dispatcher = _RecordingDispatcher(exc=RuntimeError("boom"))
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        exchange = _make_exchange({"k": 1})

        await processor.process(exchange, ExecutionContext())
        await dispatcher.wait_dispatched()
        await asyncio.sleep(0)


@pytest.mark.asyncio
class TestExchangeProperties:
    async def test_records_task_ref_in_properties(self) -> None:
        dispatcher = _RecordingDispatcher()
        processor = InvokeAsyncProcessor(
            action="x",
            dispatcher=dispatcher,  # type: ignore[arg-type]
        )
        exchange = _make_exchange({"k": 1})
        await processor.process(exchange, ExecutionContext())
        tasks = exchange.properties.get("invoke_async_tasks")
        assert isinstance(tasks, list)
        assert len(tasks) == 1
        assert tasks[0].startswith("invoke_async:x:")
