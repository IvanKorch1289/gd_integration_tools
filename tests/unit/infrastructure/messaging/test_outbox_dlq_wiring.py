"""FW1: тесты wiring InboxDLQWriter → OutboxDispatcher DLQ.

Post-FW1: ``start_outbox_dispatcher`` пытается построить ``InboxDLQWriter``
из ``state.outbox_dlq_session_factory`` (если зарегистрирован).
Pre-FW1: всегда fallback к ``_BackendDLQHandler`` (та же outbox-таблица).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest



def test_build_default_dlq_returns_none_without_session_factory() -> None:
    """Без ``outbox_dlq_session_factory`` → ``None`` (fallback к default)."""
    from src.backend.infrastructure.messaging.outbox.lifecycle import (
        _build_default_dlq_handler,
    )

    state = MagicMock(spec=[])  # no attributes
    result = _build_default_dlq_handler(state)
    assert result is None


def test_build_default_dlq_returns_none_when_state_has_no_factory() -> None:
    """``getattr`` возвращает ``None`` → ``None`` (не AttributeError)."""
    from src.backend.infrastructure.messaging.outbox.lifecycle import (
        _build_default_dlq_handler,
    )

    state = MagicMock()
    state.configure_mock(outbox_dlq_session_factory=None)
    result = _build_default_dlq_handler(state)
    assert result is None


def test_build_default_dlq_returns_adapter_when_factory_present() -> None:
    """С ``outbox_dlq_session_factory`` → возвращается _InboxAdapter."""
    from src.backend.infrastructure.messaging.outbox.lifecycle import (
        _build_default_dlq_handler,
    )

    state = MagicMock()
    state.configure_mock(outbox_dlq_session_factory=lambda: None)
    result = _build_default_dlq_handler(state)

    # Should return a non-None adapter (not the InboxDLQWriter itself,
    # but a DLQHandler-compatible wrapper).
    assert result is not None
    # Must have .send() method (DLQHandler contract).
    assert hasattr(result, "send")
    assert callable(result.send)


@pytest.mark.asyncio
async def test_inbox_adapter_sends_envelope_to_writer() -> None:
    """``_InboxAdapter.send(event, reason)`` конвертирует в DLQEnvelope и
    вызывает ``writer.write(envelope)`` с правильными полями.
    """
    from src.backend.infrastructure.messaging.dlq_base import DLQReason
    from src.backend.infrastructure.messaging.outbox.lifecycle import (
        _build_default_dlq_handler,
    )

    write_calls: list = []

    class _FakeWriter:
        def __init__(self, *, session_factory=None) -> None:
            # Match InboxDLQWriter signature.
            pass

        async def write(self, envelope) -> None:
            write_calls.append(envelope)

    class _FakeSessionFactory:
        pass

    state = MagicMock()
    # Подменяем InboxDLQWriter на _FakeWriter через monkeypatch.
    from src.backend.infrastructure.messaging.dlq import inbox_writer

    real_writer_cls = inbox_writer.InboxDLQWriter
    inbox_writer.InboxDLQWriter = _FakeWriter  # type: ignore[assignment]
    try:
        state.configure_mock(outbox_dlq_session_factory=_FakeSessionFactory())
        adapter = _build_default_dlq_handler(state)
        assert adapter is not None

        # Симулируем OutboxEvent через MagicMock.
        from dataclasses import dataclass

        @dataclass
        class FakeEvent:
            id: int = 42
            topic: str = "orders.created"
            payload: dict = None
            retry_count: int = 3

            def __post_init__(self) -> None:
                if self.payload is None:
                    self.payload = {"order_id": 1}

        event = FakeEvent()
        reason = ConnectionError("backend down")

        await adapter.send(event, reason)
    finally:
        inbox_writer.InboxDLQWriter = real_writer_cls  # type: ignore[assignment]

    assert len(write_calls) == 1
    envelope = write_calls[0]
    assert envelope.transport == "outbox"
    assert envelope.route_id == "orders.created"
    assert envelope.error_class == "ConnectionError"
    assert "backend down" in envelope.error_message
    assert envelope.reason == DLQReason.RETRIES_EXHAUSTED
    assert envelope.retry_count == 3
    assert envelope.metadata["outbox_id"] == 42
    assert envelope.metadata["outbox_topic"] == "orders.created"
