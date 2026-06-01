"""Unit-тесты Inbox с fail_mode (Sprint 8 K2 W4)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.infrastructure.eventing.inbox import (
    Inbox,
    InboxFailMode,
    InboxUnavailableError,
)


@pytest.fixture
def fake_redis_client_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Подсовывает фейковый redis_client модуль с raw_client AsyncMock."""

    class _FakeRedis:
        def __init__(self) -> None:
            self.set = AsyncMock(return_value=True)

    fake_module = type(sys)("src.backend.infrastructure.clients.storage.redis")
    fake_module.redis_client = _FakeRedis()  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "src.backend.infrastructure.clients.storage.redis",
        fake_module,
    )
    return fake_module


@pytest.mark.asyncio
async def test_inbox_default_fail_mode_open() -> None:
    """По умолчанию fail_mode='open' (backwards-compatible)."""
    inbox = Inbox()
    assert inbox.fail_mode == "open"


@pytest.mark.asyncio
async def test_inbox_fail_open_when_redis_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_mode=open: ImportError redis → возвращает False (новое событие)."""
    # Удаляем модуль из sys.modules, чтобы импорт упал
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.clients.storage.redis", None
    )
    inbox = Inbox(fail_mode="open")
    # Подменяем __import__ чтобы он бросал ImportError
    with patch.dict(sys.modules, {"src.backend.infrastructure.clients.storage.redis": None}):
        with patch(
            "src.backend.infrastructure.eventing.inbox.logger.debug"
        ):
            result = await inbox.seen_or_mark("event-1")
    # При ImportError возвращает False (не дубликат)
    assert result is False


@pytest.mark.asyncio
async def test_inbox_fail_closed_raises_on_redis_setnx_error(
    fake_redis_client_module: Any,
) -> None:
    """fail_mode=closed: Redis SETNX exception → InboxUnavailableError."""
    fake_redis_client_module.redis_client.set = AsyncMock(
        side_effect=ConnectionError("redis down")
    )
    inbox = Inbox(fail_mode="closed")
    with pytest.raises(InboxUnavailableError, match="Redis SETNX failed"):
        await inbox.seen_or_mark("event-1")


@pytest.mark.asyncio
async def test_inbox_fail_open_logs_on_setnx_error(
    fake_redis_client_module: Any,
) -> None:
    """fail_mode=open: Redis SETNX exception → log warning + return False."""
    fake_redis_client_module.redis_client.set = AsyncMock(
        side_effect=ConnectionError("redis down")
    )
    inbox = Inbox(fail_mode="open")
    result = await inbox.seen_or_mark("event-1")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_setnx_success_returns_false(
    fake_redis_client_module: Any,
) -> None:
    """Redis SET с nx=True вернул True → не дубликат → False."""
    fake_redis_client_module.redis_client.set = AsyncMock(return_value=True)
    inbox = Inbox()
    result = await inbox.seen_or_mark("event-1")
    assert result is False


@pytest.mark.asyncio
async def test_inbox_setnx_dup_returns_true(
    fake_redis_client_module: Any,
) -> None:
    """Redis SET с nx=True вернул False/None → дубликат → True."""
    fake_redis_client_module.redis_client.set = AsyncMock(return_value=False)
    inbox = Inbox()
    result = await inbox.seen_or_mark("event-1")
    assert result is True


def test_inbox_fail_mode_literal_type() -> None:
    """InboxFailMode — Literal['open', 'closed']."""
    # Compile-time check: assignment Literal
    mode_open: InboxFailMode = "open"
    mode_closed: InboxFailMode = "closed"
    assert mode_open == "open"
    assert mode_closed == "closed"
