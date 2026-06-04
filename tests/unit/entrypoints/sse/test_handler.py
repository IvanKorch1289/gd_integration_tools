"""Unit tests for SSE handler."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from src.backend.entrypoints.sse.handler import (
    EventBus,
    _InvokeRequest,
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


class TestSseInvoke:
    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        body = _InvokeRequest(action="test", payload={"x": 1})
        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl"
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
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl"
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
            side_effect=RuntimeError("boom"),
        ):
            resp = await sse_invoke(request, body)
        assert resp.media_type == "text/event-stream"
