"""Focused tests for SSESource (PERF-6.6 Sprint 20 coverage ratchet).

2026-09-11: переписаны под текущий контракт — SSEEvent(data, event_id,
event_type, timestamp) без id/retry/str/to_dict; SSESource без
retry_ms/timeout/buffer_size, _stopped — asyncio.Event (stop() → set()).
"""

from __future__ import annotations

import dataclasses

from src.backend.infrastructure.sources.sse import SSEEvent, SSESource


def test_sse_event_init_minimal() -> None:
    """SSEEvent minimal init (только data)."""
    ev = SSEEvent(data="hello")
    assert ev.data == "hello"
    assert ev.event_id is None
    assert ev.event_type == "message"
    assert ev.timestamp > 0


def test_sse_event_init_with_id_and_type() -> None:
    """SSEEvent init с event_id + event_type."""
    ev = SSEEvent(data="hello", event_id="123", event_type="update")
    assert ev.event_id == "123"
    assert ev.event_type == "update"


def test_sse_event_init_full() -> None:
    """SSEEvent init со всеми полями (data — dict для parse_json)."""
    ev = SSEEvent(data={"k": "v"}, event_id="42", event_type="alert", timestamp=1.5)
    assert ev.data == {"k": "v"}
    assert ev.event_id == "42"
    assert ev.timestamp == 1.5


def test_sse_event_is_dataclass() -> None:
    """SSEEvent — dataclass (поля сериализуются asdict)."""
    ev = SSEEvent(data="y", event_id="42", event_type="x")
    d = dataclasses.asdict(ev)
    assert d["data"] == "y"
    assert d["event_id"] == "42"
    assert d["event_type"] == "x"


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
    """SSESource init — _stopped Event не set (source активен)."""
    src = SSESource(url="https://example.com/events")
    assert src._stopped.is_set() is False


def test_sse_source_init_with_reconnect_options() -> None:
    """SSESource init с reconnect/heartbeat опциями."""
    src = SSESource(
        url="https://example.com/events",
        heartbeat_timeout_s=30.0,
        reconnect_max_retries=5,
        reconnect_initial_delay_s=0.5,
    )
    assert src._heartbeat_timeout_s == 30.0
    assert src._reconnect_max_retries == 5
    assert src._reconnect_initial_delay_s == 0.5


def test_sse_source_stop_marks_stopped() -> None:
    """stop() выставляет _stopped Event."""
    src = SSESource(url="https://example.com/events")
    src.stop()
    assert src._stopped.is_set() is True


def test_health_fast_mode() -> None:
    """health(fast) — stateless источник всегда ok."""
    src = SSESource(url="https://example.com/events")

    async def run() -> object:
        return await src.health(mode="fast")

    import asyncio

    result = asyncio.run(run())
    assert result.status == "ok"  # type: ignore[attr-defined]


def test_sse_source_state_transitions() -> None:
    """SSESource state transitions: init (unset) → stop (set)."""
    src = SSESource(url="https://example.com/events")
    assert src._stopped.is_set() is False
    src.stop()
    assert src._stopped.is_set() is True


def test_sse_source_init_parse_json_flag() -> None:
    """SSESource init с parse_json=False сохраняется."""
    src = SSESource(url="https://example.com/events", parse_json=False)
    assert src._parse_json is False


def test_sse_source_init_last_event_id() -> None:
    """SSESource init с last_event_id (resume через Last-Event-ID)."""
    src = SSESource(url="https://example.com/events", last_event_id="abc-1")
    assert src._last_event_id == "abc-1"
