"""Unit tests for src.backend.services.sources.adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.interfaces.source import SourceEvent, SourceKind
from src.backend.services.sources.adapter import SourceToInvokerAdapter


def _make_event(**kwargs: object) -> SourceEvent:
    defaults = {
        "source_id": "src-1",
        "kind": SourceKind.WEBHOOK,
        "payload": {"x": 1},
        "event_time": datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        "event_id": "evt-1",
        "metadata": {"hdr": "v"},
    }
    defaults.update(kwargs)
    return SourceEvent(**defaults)


@pytest.mark.asyncio
class TestHandle:
    async def test_default_payload(self) -> None:
        invoker = AsyncMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i1", status=InvocationStatus.OK
            )
        )
        adapter = SourceToInvokerAdapter(invoker, "orders.pay")
        event = _make_event()
        result = await adapter.handle(event)
        assert result is not None
        assert result.status == InvocationStatus.OK
        call_req = invoker.invoke.await_args[0][0]
        assert isinstance(call_req, InvocationRequest)
        assert call_req.action == "orders.pay"
        assert call_req.mode == InvocationMode.SYNC
        assert call_req.payload["data"] == {"x": 1}
        assert call_req.payload["source_id"] == "src-1"
        assert call_req.payload["event_id"] == "evt-1"
        assert call_req.metadata == {
            "source_id": "src-1",
            "source_kind": "webhook",
            "event_id": "evt-1",
        }

    async def test_duplicate_skipped(self) -> None:
        invoker = AsyncMock()
        dedupe = AsyncMock()
        dedupe.is_duplicate = AsyncMock(return_value=True)
        adapter = SourceToInvokerAdapter(
            invoker, "orders.pay", dedupe=dedupe
        )
        event = _make_event()
        result = await adapter.handle(event)
        assert result is None
        invoker.invoke.assert_not_awaited()
        dedupe.is_duplicate.assert_awaited_once_with("webhook:src-1", "evt-1")

    async def test_not_duplicate_proceeds(self) -> None:
        invoker = AsyncMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i1", status=InvocationStatus.OK
            )
        )
        dedupe = AsyncMock()
        dedupe.is_duplicate = AsyncMock(return_value=False)
        adapter = SourceToInvokerAdapter(
            invoker, "orders.pay", dedupe=dedupe
        )
        event = _make_event()
        result = await adapter.handle(event)
        assert result is not None

    async def test_custom_mapper(self) -> None:
        invoker = AsyncMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i1", status=InvocationStatus.OK
            )
        )

        def mapper(event: SourceEvent) -> dict[str, object]:
            return {"custom": event.source_id}

        adapter = SourceToInvokerAdapter(
            invoker, "orders.pay", payload_mapper=mapper
        )
        event = _make_event()
        await adapter.handle(event)
        call_req = invoker.invoke.await_args[0][0]
        assert call_req.payload == {"custom": "src-1"}

    async def test_invoker_exception(self) -> None:
        invoker = AsyncMock()
        invoker.invoke = AsyncMock(side_effect=RuntimeError("boom"))
        adapter = SourceToInvokerAdapter(invoker, "orders.pay")
        event = _make_event()
        with pytest.raises(RuntimeError, match="boom"):
            await adapter.handle(event)

    async def test_reply_channel_passed(self) -> None:
        invoker = AsyncMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i1", status=InvocationStatus.OK
            )
        )
        adapter = SourceToInvokerAdapter(
            invoker,
            "orders.pay",
            mode=InvocationMode.ASYNC_QUEUE,
            reply_channel="q1",
        )
        event = _make_event()
        await adapter.handle(event)
        call_req = invoker.invoke.await_args[0][0]
        assert call_req.mode == InvocationMode.ASYNC_QUEUE
        assert call_req.reply_channel == "q1"
