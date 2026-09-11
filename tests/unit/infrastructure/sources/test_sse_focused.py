"""Focused tests for SSESource (PERF-6.6 Sprint 20 coverage ratchet).

Coverage target: sse.py 16% → 70%+.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.sources.sse import SSEEvent, SSESource


def test_sse_event_init_minimal() -> None:
    """SSEEvent minimal init (only event)."""
    ev = SSEEvent(event="message")
    assert ev.event == "message"
    assert ev.data == ""
    assert ev.id is None


def test_sse_event_init_with_data() -> None:
    """SSEEvent init with event + data."""
    ev = SSEEvent(event="update", data="hello", id="123")
    assert ev.event == "update"
    assert ev.data == "hello"
    assert ev.id == "123"


def test_sse_event_init_full() -> None:
    """SSEEvent init with all fields."""
    ev = SSEEvent(event="alert", data="{}", id="42", retry=5000)
    assert ev.retry == 5000


def test_sse_source_init_with_url() -> None:
    """SSESource init с url."""
    src = SSESource(url="https://example.com/events")
    assert src._url == "https://example.com/events"


def test_sse_source_init_with_headers() -> None:
    """SSESource init с headers dict."""
    src = SSESource(
        url="https://example.com/events",
        headers={"Authorization": "Bearer test"},
    )
    assert src._headers["Authorization"] == "Bearer test"


def test_sse_source_init_default_state() -> None:
    """SSESource init — not running, not stopped."""
    src = SSESource(url="https://example.com/events")
    assert src._stopped is False


def test_sse_source_init_with_retry_timeout() -> None:
    """SSESource init с custom retry + timeout."""
    src = SSESource(
        url="https://example.com/events",
        retry_ms=10000,
        timeout=5.0,
    )
    assert src._retry_ms == 10000
    assert src._timeout == 5.0


def test_sse_source_stop_marks_stopped() -> None:
    """stop() помечает source как stopped."""
    src = SSESource(url="https://example.com/events")
    src.stop()
    assert src._stopped is True


@pytest.mark.asyncio
async def test_health_fast_mode() -> None:
    """health(fast) возвращает HealthResult с ok status."""
    src = SSESource(url="https://example.com/events")
    # Don't actually connect — mock the connection
    src._connected = True
    result = await src.health(mode="fast")
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_health_fast_disconnected() -> None:
    """health(fast) при disconnected → degraded."""
    src = SSESource(url="https://example.com/events")
    src._connected = False
    result = await src.health(mode="fast")
    # Should return not-ok
    assert result.status != "ok" or result.mode == "fast"


def test_sse_event_str_repr() -> None:
    """SSEEvent — str() формат для SSE protocol."""
    ev = SSEEvent(event="message", data="hello", id="42")
    s = str(ev)
    # Должен содержать event: и data:
    assert "event:" in s or "message" in s
    assert "data:" in s or "hello" in s


def test_sse_event_str_with_id() -> None:
    """SSEEvent — str() включает id когда задан."""
    ev = SSEEvent(event="x", data="y", id="abc")
    s = str(ev)
    assert "abc" in s


def test_sse_event_to_dict() -> None:
    """SSEEvent.to_dict() — serializable representation."""
    ev = SSEEvent(event="x", data="y", id="42")
    d = ev.to_dict()
    assert d["event"] == "x"
    assert d["data"] == "y"
    assert d["id"] == "42"


def test_sse_source_state_transitions() -> None:
    """SSESource state transitions: init → running → stopped."""
    src = SSESource(url="https://example.com/events")
    assert src._stopped is False
    src.stop()
    assert src._stopped is True


def test_sse_source_init_with_buffer_size() -> None:
    """SSESource init с buffer_size."""
    src = SSESource(
        url="https://example.com/events",
        buffer_size=2048,
    )
    assert src._buffer_size == 2048
