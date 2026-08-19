"""Sprint 11 P1-7: документирующий test для ListenNotifyCDCBackend.replay contract.

API contract:
- ``replay()`` — **allways returns empty async iterator** (no events).
- LISTEN/NOTIFY — push-only без хранилища, replay исторически невозможен.
- Для исторических данных использовать PollCDCBackend / DebeziumEventsCDCBackend.

Test guards against regressions:
- Если кто-то изменит ``return; yield`` pattern на ``raise NotImplementedError``,
  contract сломается (async for упадёт с TypeError).
- Если кто-то уберёт warning — операторы не узнают о необходимости fallback.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_replay_is_async_generator_function() -> None:
    """``replay()`` должен быть async generator function (PEP 525)."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    backend = ListenNotifyCDCBackend(dsn="postgresql://test")
    assert inspect.isasyncgenfunction(backend.replay), (
        "replay() должен быть async generator (для ``async for event in replay()``)"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_yields_no_events() -> None:
    """``replay()`` всегда возвращает 0 events (LISTEN/NOTIFY live-stream only)."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    backend = ListenNotifyCDCBackend(dsn="postgresql://test")
    events = []
    async for event in backend.replay(start_cursor=None, end_cursor=None):
        events.append(event)
    assert events == [], (
        f"ListenNotifyCDCBackend.replay должен быть empty, got {len(events)} events"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_emits_warning() -> None:
    """``replay()`` должен логировать warning с указанием fallback backends."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    backend = ListenNotifyCDCBackend(dsn="postgresql://test")
    with patch(
        "src.backend.infrastructure.cdc.listen_notify_backend._logger"
    ) as mock_logger:
        async for _ in backend.replay(start_cursor=None, end_cursor=None):
            pass
        # Проверяем что warning был вызван с упоминанием fallback
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args.args[0]
        assert "not supported" in warning_msg
        assert "PollCDCBackend" in warning_msg
        assert "DebeziumEventsCDCBackend" in warning_msg


@pytest.mark.unit
def test_replay_docstring_mentions_alternative_backends() -> None:
    """Docstring ``replay()`` должен явно упоминать альтернативные backends."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    docstring = ListenNotifyCDCBackend.replay.__doc__ or ""
    # Backend names OR generic terms — оба варианта приемлемы
    has_poll = "PollCDCBackend" in docstring or "Polling" in docstring
    has_debezium = "DebeziumEventsCDCBackend" in docstring or "Debezium" in docstring
    has_stream_only = "live-stream" in docstring or "невозможен" in docstring
    assert has_poll, f"Docstring должен упоминать PollCDCBackend/Polling, got: {docstring!r}"
    assert has_debezium, f"Docstring должен упоминать Debezium, got: {docstring!r}"
    assert has_stream_only, f"Docstring должен указывать live-stream limitation, got: {docstring!r}"
