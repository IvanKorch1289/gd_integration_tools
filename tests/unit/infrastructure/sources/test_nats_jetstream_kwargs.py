"""Tests for ``src.backend.infrastructure.sources.nats_jetstream``.

Критичный regression: ``NatsJetStreamSource.start()`` вызывает
:class:`SourceEvent` с НЕПРАВИЛЬНЫМ kwarg name:
- ``timestamp=nats_msg.timestamp`` (нет такого поля; должно быть ``event_time=``)
- отсутствует ``event_id`` (требуется для idempotency)

SourceEvent — ``@dataclass(slots=True)``, не Pydantic. ``slots=True``
отвергает неизвестные kwargs с ``TypeError`` (а не silent ignore).

Bugfix contract: SourceEvent требует ``event_time`` и ``event_id``;
``timestamp`` недопустим.
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.interfaces.source import SourceEvent
from src.backend.infrastructure.sources.nats_jetstream import (
    NATSJetStreamSource,
)


class TestNatsJetStreamSourceEventKwargs:
    """``start()`` должен передавать в SourceEvent только допустимые kwargs."""

    @pytest.mark.asyncio
    async def test_source_event_accepts_kwargs_from_start(self) -> None:
        """Контракт: ``start()`` НЕ бросает TypeError при конструировании
        SourceEvent.

        Раньше start() вызывал SourceEvent с ``timestamp=`` (нет такого
        поля) → TypeError. После fix — использует ``event_time`` (datetime)
        и ``event_id`` (str) → SourceEvent конструируется успешно.
        """
        nats_msg = MagicMock()
        nats_msg.data = b"payload"
        nats_msg.subject = "test.subject"
        nats_msg.timestamp = 1234567890.0
        nats_msg.headers = None
        nats_msg.reply = None

        source = NATSJetStreamSource(
            subject="test.subject",
            stream="TEST",
            durable="durable-1",
        )
        async def fake_stream():
            yield nats_msg
            return

        source.stream = fake_stream  # type: ignore[method-assign]

        on_event = AsyncMock()

        # Не должно быть TypeError (раньше был из-за timestamp=)
        try:
            await source.start(on_event)
        except TypeError as exc:
            pytest.fail(
                f"NatsJetStreamSource.start() упал с TypeError: {exc}. "
                "Скорее всего возвращается regression: kwargs для "
                "SourceEvent не соответствуют signature."
            )

    @pytest.mark.asyncio
    async def test_source_event_uses_event_time_not_timestamp(self) -> None:
        """Регрессионный тест: после fix ``timestamp=`` → ``event_time=``.

        SourceEvent требует ``event_time`` (datetime). Проверяем что
        NatsJetStreamSource использует правильное имя.
        """
        nats_msg = MagicMock()
        nats_msg.data = b"payload"
        nats_msg.subject = "test.subject"
        nats_msg.timestamp = 1234567890.0
        nats_msg.headers = None
        nats_msg.reply = None

        source = NATSJetStreamSource(
            subject="test.subject",
            stream="TEST",
            durable="durable-1",
        )

        # Capture event
        captured: list[SourceEvent] = []

        async def fake_on_event(event: SourceEvent) -> None:
            captured.append(event)

        async def fake_stream():
            yield nats_msg
            return

        source.stream = fake_stream  # type: ignore[method-assign]

        # Не должно быть TypeError
        try:
            await source.start(fake_on_event)
        except TypeError as exc:
            pytest.fail(
                f"NatsJetStreamSource.start() упал с TypeError: {exc}. "
                "Скорее всего передаётся 'timestamp' вместо 'event_time' "
                "в SourceEvent."
            )

        # event должен быть валидным
        assert len(captured) == 1, f"Expected 1 event, got {len(captured)}"
        event = captured[0]
        # event_time должен быть заполнен (из nats_msg.timestamp)
        assert isinstance(event.event_time, datetime), (
            f"event.event_time should be datetime, got {type(event.event_time)}"
        )
        # event_id должен быть заполнен (auto-generated)
        assert isinstance(event.event_id, str)
        assert len(event.event_id) > 0


class TestSourceEventKwargsContract:
    """Дополнительные тесты на контракт SourceEvent kwargs."""

    def test_source_event_accepts_event_time(self) -> None:
        """SourceEvent принимает ``event_time`` kwarg."""
        ts = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
        event = SourceEvent(
            source_id="src-1",
            kind="nats",
            payload=b"data",
            event_time=ts,
        )
        assert event.event_time == ts

    def test_source_event_does_not_accept_timestamp(self) -> None:
        """SourceEvent НЕ принимает ``timestamp`` kwarg (документированный
        контракт: SourceEvent — это generic event type, не имеет
        timestamp-specific field).
        """
        with pytest.raises(TypeError):
            SourceEvent(
                source_id="src-1",
                kind="nats",
                payload=b"data",
                timestamp=1234567890.0,  # type: ignore[call-arg]
            )
