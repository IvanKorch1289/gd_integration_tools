"""Coverage ratchet для streaming_llm_publishers.py (Sprint 12, cycle 148).

Покрывает branch'и, не покрытые существующими deadline-focused тестами:
- ``SSEPublisher.publish_chunk / publish_done`` (lines 34-46).
- ``WSPublisher.publish_chunk / publish_done`` (lines 54-66).
- ``_BasePublisher.publish_chunk / publish_done`` (lines 20-26) — abstract.
- ``WebhookChunkedPublisher.publish_chunk / publish_done`` без URL (lines 119-131).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message


def _make_exchange(props: dict[str, Any] | None = None) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body={}))
    ex.status = ExchangeStatus.processing
    if props:
        ex.properties.update(props)
    return ex


# ============================================================================
# _BasePublisher (abstract)
# ============================================================================


class TestBasePublisher:
    """``_BasePublisher`` abstract methods raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_publish_chunk_raises(self) -> None:
        """Default publish_chunk → NotImplementedError."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            _BasePublisher,
        )

        pub = _BasePublisher()
        with pytest.raises(NotImplementedError):
            await pub.publish_chunk(exchange=_make_exchange(), chunk={"delta": "x"})

    @pytest.mark.asyncio
    async def test_publish_done_raises(self) -> None:
        """Default publish_done → NotImplementedError."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            _BasePublisher,
        )

        pub = _BasePublisher()
        with pytest.raises(NotImplementedError):
            await pub.publish_done(exchange=_make_exchange(), finish_reason="stop")


# ============================================================================
# SSEPublisher
# ============================================================================


class TestSSEPublisher:
    """``SSEPublisher`` — append events to sse_events list property."""

    @pytest.mark.asyncio
    async def test_publish_chunk_appends_delta_event(self) -> None:
        """publish_chunk → append {'event': 'delta', 'data': chunk.delta}."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
        )

        pub = SSEPublisher()
        ex = _make_exchange()
        await pub.publish_chunk(exchange=ex, chunk={"delta": "hello"})
        events = ex.get_property("sse_events")
        assert events == [{"event": "delta", "data": "hello"}]

    @pytest.mark.asyncio
    async def test_publish_chunk_appends_multiple(self) -> None:
        """Multiple chunks → multiple events в list."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
        )

        pub = SSEPublisher()
        ex = _make_exchange()
        await pub.publish_chunk(exchange=ex, chunk={"delta": "a"})
        await pub.publish_chunk(exchange=ex, chunk={"delta": "b"})
        await pub.publish_chunk(exchange=ex, chunk={"delta": "c"})
        events = ex.get_property("sse_events")
        assert events == [
            {"event": "delta", "data": "a"},
            {"event": "delta", "data": "b"},
            {"event": "delta", "data": "c"},
        ]

    @pytest.mark.asyncio
    async def test_publish_done_appends_done_event(self) -> None:
        """publish_done → append {'event': 'done', 'data': finish_reason}."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
        )

        pub = SSEPublisher()
        ex = _make_exchange()
        await pub.publish_done(exchange=ex, finish_reason="stop")
        events = ex.get_property("sse_events")
        assert events == [{"event": "done", "data": "stop"}]

    @pytest.mark.asyncio
    async def test_publish_done_with_empty_events_creates_list(self) -> None:
        """publish_done без предшествующих chunks → создаёт пустой sse_events."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
        )

        pub = SSEPublisher()
        ex = _make_exchange()
        await pub.publish_done(exchange=ex, finish_reason="length")
        events = ex.get_property("sse_events")
        assert events == [{"event": "done", "data": "length"}]

    @pytest.mark.asyncio
    async def test_publish_done_after_chunks(self) -> None:
        """Sequence: chunks + done → events содержит все."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
        )

        pub = SSEPublisher()
        ex = _make_exchange()
        await pub.publish_chunk(exchange=ex, chunk={"delta": "x"})
        await pub.publish_chunk(exchange=ex, chunk={"delta": "y"})
        await pub.publish_done(exchange=ex, finish_reason="stop")
        events = ex.get_property("sse_events")
        assert len(events) == 3
        assert events[-1] == {"event": "done", "data": "stop"}


# ============================================================================
# WSPublisher
# ============================================================================


class TestWSPublisher:
    """``WSPublisher`` — invokes ws_send callable from property."""

    @pytest.mark.asyncio
    async def test_publish_chunk_invokes_ws_send(self) -> None:
        """publish_chunk → вызывает ws_send callable с delta payload."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WSPublisher,
        )

        sent: list[dict[str, Any]] = []

        async def ws_send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        pub = WSPublisher()
        ex = _make_exchange({"ws_send": ws_send})
        await pub.publish_chunk(exchange=ex, chunk={"delta": "hello"})
        assert sent == [{"type": "delta", "delta": "hello"}]

    @pytest.mark.asyncio
    async def test_publish_chunk_no_ws_send_is_noop(self) -> None:
        """publish_chunk без ws_send → silent no-op (не raise)."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WSPublisher,
        )

        pub = WSPublisher()
        ex = _make_exchange()  # без ws_send
        # Не должно бросить исключение.
        await pub.publish_chunk(exchange=ex, chunk={"delta": "x"})

    @pytest.mark.asyncio
    async def test_publish_done_invokes_ws_send(self) -> None:
        """publish_done → вызывает ws_send с finish_reason."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WSPublisher,
        )

        sent: list[dict[str, Any]] = []

        async def ws_send(payload: dict[str, Any]) -> None:
            sent.append(payload)

        pub = WSPublisher()
        ex = _make_exchange({"ws_send": ws_send})
        await pub.publish_done(exchange=ex, finish_reason="stop")
        assert sent == [{"type": "done", "finish_reason": "stop"}]

    @pytest.mark.asyncio
    async def test_publish_done_no_ws_send_is_noop(self) -> None:
        """publish_done без ws_send → silent no-op."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WSPublisher,
        )

        pub = WSPublisher()
        ex = _make_exchange()
        await pub.publish_done(exchange=ex, finish_reason="length")


# ============================================================================
# WebhookChunkedPublisher (no-url cases)
# ============================================================================


class TestWebhookChunkedPublisherNoUrl:
    """``WebhookChunkedPublisher.publish_chunk/done`` без URL → silent no-op."""

    @pytest.mark.asyncio
    async def test_publish_chunk_no_url_is_noop(self) -> None:
        """publish_chunk без webhook_url → no-op (без _send)."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher()
        ex = _make_exchange()  # без webhook_url
        # Не должно бросить исключение, не должно пытаться делать HTTP call.
        await pub.publish_chunk(exchange=ex, chunk={"delta": "x"})

    @pytest.mark.asyncio
    async def test_publish_done_no_url_is_noop(self) -> None:
        """publish_done без webhook_url → no-op."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher()
        ex = _make_exchange()
        await pub.publish_done(exchange=ex, finish_reason="stop")

    @pytest.mark.asyncio
    async def test_publish_chunk_with_empty_url_is_noop(self) -> None:
        """publish_chunk с пустым webhook_url → no-op (truthy check)."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher()
        ex = _make_exchange({"webhook_url": ""})
        await pub.publish_chunk(exchange=ex, chunk={"delta": "x"})

    def test_default_url_property_name(self) -> None:
        """Default url_property='webhook_url'."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher()
        assert pub._url_property == "webhook_url"

    def test_custom_url_property_name(self) -> None:
        """Custom url_property сохраняется."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher(url_property="custom_url")
        assert pub._url_property == "custom_url"

    def test_default_timeout(self) -> None:
        """Default timeout=5.0 секунд."""
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            WebhookChunkedPublisher,
        )

        pub = WebhookChunkedPublisher()
        assert pub._timeout == 5.0
