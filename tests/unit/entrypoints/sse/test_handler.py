"""Unit tests for SSE handler."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import datetime
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from pydantic import BaseModel

from src.backend.entrypoints.sse.handler import (
    EventBus,
    _InvokeRequest,
    _to_primitive,
    event_bus,
    sse_invoke,
    sse_stream,
)


class TestEventBus:
    @pytest.fixture
    def bus(self) -> EventBus:
        return EventBus()

    def test_subscribe(self, bus: EventBus) -> None:
        q = bus.subscribe()
        assert q in bus._subscribers

    def test_unsubscribe(self, bus: EventBus) -> None:
        q = bus.subscribe()
        bus.unsubscribe(q)
        assert q not in bus._subscribers

    @pytest.mark.asyncio
    async def test_publish(self, bus: EventBus) -> None:
        q = bus.subscribe()
        await bus.publish("test", {"x": 1})
        assert q.qsize() == 1
        ev = q.get_nowait()
        assert ev["event"] == "test"
        assert ev["data"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_publish_drops_on_full(self, bus: EventBus) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=0)
        bus._subscribers.append(q)
        await bus.publish("test", {"x": 1})

    @pytest.mark.asyncio
    async def test_publish_warns_on_full(self, bus: EventBus) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        bus._subscribers.append(q)
        q.put_nowait({"event": "fill", "data": {}})  # fill the queue
        await bus.publish("test", {"x": 1})  # should not raise


class TestSseStream:
    @pytest.mark.asyncio
    async def test_stream_response(self) -> None:
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(return_value=True)
        request.state = MagicMock()
        request.state.pii_streaming_policy = None
        with patch(
            "src.backend.infrastructure.security.pii_streaming.stream_filter"
        ) as mock_filter:

            async def _empty():
                return
                yield  # make it an async generator

            mock_filter.return_value = _empty()
            resp = await sse_stream(request)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_raw_generator_heartbeat_on_timeout(self) -> None:
        """При отсутствии событий в течение 30s yield heartbeat."""
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(side_effect=[False, True])
        request.state = MagicMock()
        request.state.pii_streaming_policy = None

        mock_queue = MagicMock()
        mock_queue.get = AsyncMock(side_effect=TimeoutError)
        with patch.object(event_bus, "subscribe", return_value=mock_queue):
            resp = await sse_stream(request)

        # Прочитаем первый chunk из generator — должен быть heartbeat
        body = []
        async for chunk in resp.body_iterator:
            body.append(chunk)
            break  # достаточно одного heartbeat
        assert ": heartbeat" in "".join(body)
        mock_queue.get.assert_awaited()

    @pytest.mark.asyncio
    async def test_event_generator_fallback_on_stream_filter_error(self) -> None:
        """Если stream_filter падает — используется _raw_generator без PII."""
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(return_value=True)
        request.state = MagicMock()
        request.state.pii_streaming_policy = None
        with patch(
            "src.backend.infrastructure.security.pii_streaming.stream_filter",
            side_effect=RuntimeError("pii fail"),
        ):
            resp = await sse_stream(request)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_stream_yields_event(self) -> None:
        """PII-фильтр пропускает событие — покрывает yield chunk в try."""
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(side_effect=[False, True])
        request.state = MagicMock()
        request.state.pii_streaming_policy = None
        with patch(
            "src.backend.infrastructure.security.pii_streaming.stream_filter"
        ) as mock_filter:

            async def _fake(*args: Any, **kwargs: Any) -> Any:
                yield "event: msg\ndata: {}\n\n"

            mock_filter.side_effect = _fake
            resp = await sse_stream(request)
            # Итерируем внутри with, т.к. event_generator() делает lazy import stream_filter
            chunks = [c async for c in resp.body_iterator]
        assert "event: msg" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_raw_generator_receives_event(self) -> None:
        """Queue возвращает событие без timeout — покрывает await wait_for."""
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(side_effect=[False, True])
        request.state = MagicMock()
        request.state.pii_streaming_policy = None
        real_queue = asyncio.Queue()
        await real_queue.put({"event": "msg", "data": {"x": 1}})
        with patch.object(event_bus, "subscribe", return_value=real_queue):
            resp = await sse_stream(request)
        chunks = [c async for c in resp.body_iterator]
        assert "event: msg" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_event_generator_fallback_yields_raw(self) -> None:
        """Fallback на _raw_generator при ошибке stream_filter yield событие."""
        request = MagicMock(spec=Request)
        request.is_disconnected = AsyncMock(side_effect=[False, True])
        request.state = MagicMock()
        request.state.pii_streaming_policy = None
        mock_queue = MagicMock()
        mock_queue.get = AsyncMock(return_value={"event": "msg", "data": {}})
        with patch.object(event_bus, "subscribe", return_value=mock_queue):
            with patch(
                "src.backend.infrastructure.security.pii_streaming.stream_filter",
                side_effect=RuntimeError("pii fail"),
            ):
                resp = await sse_stream(request)
                # Итерируем внутри with, т.к. event_generator() делает lazy import stream_filter
                chunks = [c async for c in resp.body_iterator]
        assert "event: msg" in "".join(chunks)


class TestSseInvoke:
    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={"x": 1})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={"result": 42}, error=None, error_code=None
            )
            resp = await sse_invoke(request, body)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_invoke_error(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=False, data=None, error="fail", error_code="err"
            )
            resp = await sse_invoke(request, body)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_invoke_exception(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await sse_invoke(request, body)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_invoke_passes_correlation_and_idempotency(self) -> None:
        """correlation_id и idempotency_key передаются в bridge."""
        request = MagicMock(spec=Request)
        request.headers = {
            "x-correlation-id": "corr-123",
            "idempotency-key": "idem-456",
        }
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={}, error=None, error_code=None
            )
            resp = await sse_invoke(request, body)
            # Итерируем body_iterator внутри with, чтобы мок был активен
            _ = [c async for c in resp.body_iterator]
        mock_bridge.assert_called_once()
        call_kwargs = mock_bridge.call_args.kwargs
        assert call_kwargs["correlation_id"] == "corr-123"
        assert call_kwargs["idempotency_key"] == "idem-456"

    @pytest.mark.asyncio
    async def test_invoke_success_stream_contents(self) -> None:
        """Поток при success содержит start, result, end."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={"ok": True}, error=None, error_code=None
            )
            resp = await sse_invoke(request, body)
            chunks = [c async for c in resp.body_iterator]
        text = "".join(chunks)
        assert "event: start" in text
        assert "event: result" in text
        assert '"ok":true' in text
        assert "event: end" in text

    @pytest.mark.asyncio
    async def test_invoke_error_stream_contents(self) -> None:
        """Поток при bridge.error содержит start, error, end."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=False, data=None, error="fail", error_code="err_code"
            )
            resp = await sse_invoke(request, body)
            chunks = [c async for c in resp.body_iterator]
        text = "".join(chunks)
        assert "event: start" in text
        assert "event: error" in text
        assert "fail" in text
        assert "event: end" in text

    @pytest.mark.asyncio
    async def test_invoke_exception_stream_contents(self) -> None:
        """Поток при exception содержит start, error, end."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await sse_invoke(request, body)
            chunks = [c async for c in resp.body_iterator]
        text = "".join(chunks)
        assert "event: start" in text
        assert "event: error" in text
        assert "boom" in text
        assert "event: end" in text

    @pytest.mark.asyncio
    async def test_invoke_success_with_datetime(self) -> None:
        """datetime в bridge.data сериализуется в ISO-формат через _to_primitive."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        now = datetime.datetime(2026, 6, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={"created_at": now}, error=None, error_code=None
            )
            resp = await sse_invoke(request, body)
            chunks = [c async for c in resp.body_iterator]
        text = "".join(chunks)
        assert "event: start" in text
        assert "event: result" in text
        assert "2026-06-05T12:00:00+00:00" in text
        assert "event: end" in text

    @pytest.mark.asyncio
    async def test_invoke_success_with_enum(self) -> None:
        """Enum в bridge.data сериализуется как value через _to_primitive."""

        class Status(Enum):
            OK = "ok"

        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={"status": Status.OK}, error=None, error_code=None
            )
            resp = await sse_invoke(request, body)
            chunks = [c async for c in resp.body_iterator]
        text = "".join(chunks)
        assert "event: start" in text
        assert "event: result" in text
        assert '"status":"ok"' in text
        assert "event: end" in text


class TestToPrimitive:
    def test_base_model(self) -> None:
        class Item(BaseModel):
            name: str
            count: int

        assert _to_primitive(Item(name="x", count=1)) == {"name": "x", "count": 1}

    def test_datetime(self) -> None:
        now = datetime.datetime(2026, 6, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        assert _to_primitive(now) == "2026-06-05T12:00:00+00:00"

    def test_enum(self) -> None:
        class Color(Enum):
            RED = 1

        assert _to_primitive(Color.RED) == 1

    def test_nested(self) -> None:
        class Item(BaseModel):
            name: str

        nested = {
            "items": [Item(name="a")],
            "meta": {"ts": datetime.datetime(2026, 1, 1)},
        }
        assert _to_primitive(nested) == {
            "items": [{"name": "a"}],
            "meta": {"ts": "2026-01-01T00:00:00"},
        }
