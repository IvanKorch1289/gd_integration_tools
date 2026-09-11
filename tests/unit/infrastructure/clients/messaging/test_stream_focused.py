"""Focused tests for ``stream`` module (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/infrastructure/clients/messaging/stream.py``
с ~24% до ≥60% путём тестирования StreamMessage, BreakerSpec, StreamClient.

Контракт API (см. stream.py):
- ``StreamMessage(raw_message, body, *, headers, reply_to, ...)`` — обёртка.
- ``StreamMessage.ack()``, ``nack()``, ``reject()`` — async ack-control.
- ``StreamMessage.decode()`` — async, декодирует body через async decoder.
- ``BreakerSpec(name='default', failure_threshold=5, recovery_timeout=30.0, ...)`` — CB spec.
- ``StreamClient.health_check()`` — health probe.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.clients.messaging.stream import (
    BreakerSpec,
    StreamClient,
    StreamMessage,
)


class TestStreamMessageInit:
    """``StreamMessage.__init__`` — конструктор и defaults."""

    def test_init_minimal(self) -> None:
        """``StreamMessage`` создаётся только с ``raw_message`` + ``body``."""
        msg = StreamMessage(raw_message=object(), body=b"hello")
        assert msg.body == b"hello"
        # defaults (от FastStream parent).
        assert msg.headers == {}
        assert msg.path == {}
        assert msg.reply_to == ""
        assert msg.batch_headers == []
        assert msg.content_type is None
        # correlation_id/message_id генерируются автоматически.
        assert msg.correlation_id is not None
        assert msg.message_id is not None

    def test_init_with_headers(self) -> None:
        """``StreamMessage.headers`` сохраняет кастомный dict."""
        msg = StreamMessage(
            raw_message=object(),
            body=b"x",
            headers={"x-trace": "abc", "x-user": "u1"},
        )
        assert msg.headers == {"x-trace": "abc", "x-user": "u1"}

    def test_init_with_reply_to(self) -> None:
        """``StreamMessage.reply_to`` сохраняет имя reply-канала."""
        msg = StreamMessage(
            raw_message=object(), body=b"x", reply_to="events.replies.uuid-1"
        )
        assert msg.reply_to == "events.replies.uuid-1"

    def test_init_with_correlation_id(self) -> None:
        """``StreamMessage.correlation_id`` сохраняет переданный ID."""
        msg = StreamMessage(
            raw_message=object(), body=b"x", correlation_id="my-cid"
        )
        assert msg.correlation_id == "my-cid"

    def test_init_with_message_id(self) -> None:
        """``StreamMessage.message_id`` сохраняет переданный ID."""
        msg = StreamMessage(
            raw_message=object(), body=b"x", message_id="my-mid"
        )
        assert msg.message_id == "my-mid"

    def test_init_with_content_type(self) -> None:
        """``StreamMessage.content_type`` сохраняется."""
        msg = StreamMessage(
            raw_message=object(), body=b"x", content_type="application/json"
        )
        assert msg.content_type == "application/json"

    def test_init_with_dict_body(self) -> None:
        """``StreamMessage.body`` может быть dict (не только bytes)."""
        msg = StreamMessage(raw_message=object(), body={"k": "v"})
        assert msg.body == {"k": "v"}


class TestStreamMessageAckControl:
    """``ack()`` / ``nack()`` / ``reject()`` — best-effort control (async)."""

    async def test_ack_no_raw_message_no_error(self) -> None:
        """``ack()`` без raw_message — no-op, не падает."""
        msg = StreamMessage(raw_message=None, body=b"x")
        await msg.ack()  # не должно бросить

    async def test_nack_no_raw_message_no_error(self) -> None:
        """``nack()`` без raw_message — no-op."""
        msg = StreamMessage(raw_message=None, body=b"x")
        await msg.nack()

    async def test_reject_no_raw_message_no_error(self) -> None:
        """``reject()`` без raw_message — no-op."""
        msg = StreamMessage(raw_message=None, body=b"x")
        await msg.reject()

    async def test_ack_with_raw_message_no_ack_method(self) -> None:
        """``ack()`` с raw_message без ``ack()`` method — no-op."""
        msg = StreamMessage(raw_message=object(), body=b"x")
        # object() не имеет метода ``ack``, должно просто пропустить.
        await msg.ack()


class TestStreamMessageDecode:
    """``decode()`` — async body decoding через async decoder."""

    async def test_decode_with_async_decoder(self) -> None:
        """``decode()`` вызывает async decoder на msg."""
        msg = StreamMessage(raw_message=object(), body=b"raw-bytes")

        async def my_decoder(stream_msg: StreamMessage) -> str:
            return stream_msg.body.decode("utf-8")

        msg.set_decoder(my_decoder)
        decoded = await msg.decode()
        assert decoded == "raw-bytes"
        # Второй вызов вернёт cached значение.
        decoded2 = await msg.decode()
        assert decoded2 == "raw-bytes"

    async def test_decode_without_decoder_raises(self) -> None:
        """``decode()`` без decoder → AssertionError."""
        msg = StreamMessage(raw_message=object(), body=b"raw")
        # Без set_decoder — FastStream parent бросит AssertionError.
        with pytest.raises(AssertionError):
            await msg.decode()

    async def test_set_decoder_replaces(self) -> None:
        """``set_decoder()`` заменяет предыдущий decoder."""
        msg = StreamMessage(raw_message=object(), body=b"x")

        async def decoder_v1(m: StreamMessage) -> str:
            return f"v1-{m.body.decode('utf-8')}"

        async def decoder_v2(m: StreamMessage) -> str:
            return f"v2-{m.body.decode('utf-8')}"

        msg.set_decoder(decoder_v1)
        first = await msg.decode()
        assert first == "v1-x"

        # Replace.
        msg.set_decoder(decoder_v2)
        msg.clear_cache()
        decoded = await msg.decode()
        assert decoded == "v2-x"


class TestStreamMessageCache:
    """``clear_cache()`` — сброс decoded_cache."""

    async def test_clear_cache(self) -> None:
        """``clear_cache()`` очищает cache (вызов возможен до decode)."""
        call_count = 0

        async def counting_decoder(m: StreamMessage) -> bytes:
            nonlocal call_count
            call_count += 1
            return m.body + b"-decoded"

        msg = StreamMessage(raw_message=object(), body=b"x")
        msg.set_decoder(counting_decoder)
        await msg.decode()  # populates cache
        assert call_count == 1
        msg.clear_cache()
        # decode снова вызывает decoder.
        result = await msg.decode()
        assert result == b"x-decoded"
        assert call_count == 2


class TestBreakerSpec:
    """``BreakerSpec`` — конфигурация circuit breaker."""

    def test_default_values(self) -> None:
        """``BreakerSpec()`` defaults."""
        spec = BreakerSpec()
        assert spec.name == "default"
        assert spec.failure_threshold == 5
        assert spec.recovery_timeout == 30.0
        assert spec.window_seconds == 0.0
        assert spec.half_open_max_calls == 1
        assert spec.excluded_exceptions == ()

    def test_custom_values(self) -> None:
        """``BreakerSpec`` принимает кастомные параметры."""
        spec = BreakerSpec(
            name="my-cb",
            failure_threshold=10,
            recovery_timeout=60.0,
            window_seconds=120.0,
            half_open_max_calls=3,
            excluded_exceptions=(ValueError, KeyError),
        )
        assert spec.name == "my-cb"
        assert spec.failure_threshold == 10
        assert spec.recovery_timeout == 60.0
        assert spec.window_seconds == 120.0
        assert spec.half_open_max_calls == 3
        assert spec.excluded_exceptions == (ValueError, KeyError)

    def test_excluded_exceptions_default_is_empty_tuple(self) -> None:
        """``excluded_exceptions`` default — пустой tuple."""
        spec = BreakerSpec()
        assert isinstance(spec.excluded_exceptions, tuple)
        assert len(spec.excluded_exceptions) == 0


class TestStreamClient:
    """``StreamClient`` — best-effort multi-protocol publish."""

    def test_init(self) -> None:
        """``StreamClient()`` создаётся без аргументов."""
        client = StreamClient()
        assert client is not None

    async def test_health_check_no_brokers(self) -> None:
        """``health_check()`` без подключённых брокеров — degraded/unhealthy."""
        client = StreamClient()
        result = await client.health_check()
        assert isinstance(result, dict)
