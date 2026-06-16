"""Tests для SSESource + DSL from_sse builder (S94 W4)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.infrastructure.sources.sse import SSEEvent, SSESource


def _make_sse_response(lines: list[str]) -> Any:
    """Создаёт mock response с заданными SSE lines."""
    resp = type("Resp", (), {})()
    resp.raise_for_status = lambda: None

    async def aiter_lines():
        for line in lines:
            yield line

    resp.aiter_lines = aiter_lines
    return resp


class _FakeStreamCM:
    """Fake context manager для client.stream()."""

    def __init__(self, resp: Any) -> None:
        self._resp = resp

    async def __aenter__(self) -> Any:
        return self._resp

    async def __aexit__(self, *args: Any) -> None:
        pass


class _FakeAsyncClient:
    """Fake httpx.AsyncClient — поддерживает ``set_response`` для конфигурации."""

    _shared_resp: Any = None

    def __init__(self, **kwargs: Any) -> None:
        pass

    def stream(self, *args: Any, **kwargs: Any) -> _FakeStreamCM:
        return _FakeStreamCM(_FakeAsyncClient._shared_resp)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_sse_parses_simple_event() -> None:
    """Простое SSE-событие парсится в SSEEvent."""
    _FakeAsyncClient._shared_resp = _make_sse_response(["data: hello world", "", ""])
    with patch("httpx.AsyncClient", _FakeAsyncClient):
        source = SSESource(url="https://example.com/events", reconnect_max_retries=0)
        events: list[SSEEvent] = []
        async for evt in source.stream():
            events.append(evt)
            if len(events) >= 1:
                source.stop()

    assert len(events) == 1
    assert events[0].event_type == "message"
    assert events[0].data == "hello world"


@pytest.mark.asyncio
async def test_sse_parses_named_event_with_id() -> None:
    """Event с event_type + event_id."""
    _FakeAsyncClient._shared_resp = _make_sse_response(
        ["event: order.created", "id: evt-42", 'data: {"order_id": 1}', "", ""]
    )
    with patch("httpx.AsyncClient", _FakeAsyncClient):
        source = SSESource(
            url="https://example.com/events", parse_json=True, reconnect_max_retries=0
        )
        events: list[SSEEvent] = []
        async for evt in source.stream():
            events.append(evt)
            if len(events) >= 1:
                source.stop()

    assert len(events) == 1
    assert events[0].event_type == "order.created"
    assert events[0].event_id == "evt-42"
    assert events[0].data == {"order_id": 1}
    # Last-Event-ID обновлён для resume
    assert source._last_event_id == "evt-42"


@pytest.mark.asyncio
async def test_sse_multi_line_data() -> None:
    """Multi-line data: объединяется в одну строку с \\n."""
    _FakeAsyncClient._shared_resp = _make_sse_response(
        ["data: line1", "data: line2", "data: line3", "", ""]
    )
    with patch("httpx.AsyncClient", _FakeAsyncClient):
        source = SSESource(
            url="https://example.com/events", parse_json=False, reconnect_max_retries=0
        )
        events: list[SSEEvent] = []
        async for evt in source.stream():
            events.append(evt)
            if len(events) >= 1:
                source.stop()

    assert len(events) == 1
    assert events[0].data == "line1\nline2\nline3"


@pytest.mark.asyncio
async def test_sse_handles_keep_alive_comments() -> None:
    """SSE comments (``: ping``) — пропускаются."""
    _FakeAsyncClient._shared_resp = _make_sse_response(
        [": this is a comment", "data: real-event", "", ""]
    )
    with patch("httpx.AsyncClient", _FakeAsyncClient):
        source = SSESource(
            url="https://example.com/events", parse_json=False, reconnect_max_retries=0
        )
        events: list[SSEEvent] = []
        async for evt in source.stream():
            events.append(evt)
            if len(events) >= 1:
                source.stop()

    assert len(events) == 1
    assert events[0].data == "real-event"


def test_sse_source_basic_config() -> None:
    """SSESource creation: stores config, generates subscription_id."""
    src = SSESource(
        url="https://example.com/events",
        event_type="order.created",
        heartbeat_timeout_s=30.0,
    )
    assert src._url == "https://example.com/events"
    assert src._event_type == "order.created"
    assert src._heartbeat_timeout_s == 30.0
    assert src._subscription_id  # uuid assigned


def test_sse_source_stop_sets_event() -> None:
    """stop() выставляет asyncio.Event."""
    src = SSESource(url="https://example.com/events")
    assert not src._stopped.is_set()
    src.stop()
    assert src._stopped.is_set()


def test_sse_event_dataclass() -> None:
    """SSEEvent — dataclass с правильными defaults."""
    evt = SSEEvent(data="x")
    assert evt.event_type == "message"
    assert evt.event_id is None
    assert isinstance(evt.timestamp, float)


def test_dsl_sources_mixin_has_from_sse() -> None:
    """SourcesMixin имеет метод from_sse (S94 W4)."""
    from src.backend.dsl.builders.sources_mixin import SourcesMixin

    assert hasattr(SourcesMixin, "from_sse")
    import inspect

    sig = inspect.signature(SourcesMixin.from_sse)
    params = list(sig.parameters.keys())
    assert "route_id" in params
    assert "url" in params
    assert "event_type" in params
    assert "headers" in params
    assert "last_event_id" in params


def test_sse_source_rejects_invalid_event_filter() -> None:
    """SSESource с event_type='*' (special) не делает фильтрацию."""
    src = SSESource(url="https://example.com/events", event_type="*")
    # wildcard = no filter (отдаём всё caller'у)
    assert src._event_type == "*"
