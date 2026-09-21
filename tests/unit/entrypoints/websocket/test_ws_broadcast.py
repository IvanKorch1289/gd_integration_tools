"""Unit tests for ws_broadcast (cross-instance WebSocket broadcast)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.websocket.ws_broadcast import WSBroadcast, ws_broadcast


@pytest.fixture
def mock_pubsub() -> AsyncMock:
    """Returns a mocked Redis PubSub instance."""
    return AsyncMock()


@pytest.fixture
def mock_redis_set() -> AsyncMock:
    """Returns a mocked Redis Set instance."""
    return AsyncMock()


@pytest.fixture
def broadcast(mock_pubsub: AsyncMock, mock_redis_set: AsyncMock) -> WSBroadcast:
    """Returns a WSBroadcast instance with mocked Redis providers."""
    with (
        patch(
            "src.backend.entrypoints.websocket.ws_broadcast.get_redis_pubsub_factory_provider",
            return_value=lambda channel: mock_pubsub,
        ),
        patch(
            "src.backend.entrypoints.websocket.ws_broadcast.get_redis_set_factory_provider",
            return_value=lambda key: mock_redis_set,
        ),
    ):
        yield WSBroadcast()


# ─── set_local_handler ───────────────────────────────────────────────────────


def test_set_local_handler(broadcast: WSBroadcast) -> None:
    """set_local_handler stores the handler."""
    handler = AsyncMock()
    broadcast.set_local_handler(handler)
    assert broadcast._local_handler is handler


# ─── start_listener / stop_listener ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_listener_creates_task(
    broadcast: WSBroadcast, mock_pubsub: AsyncMock
) -> None:
    """start_listener creates a background task."""
    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.websocket.ws_broadcast.get_task_registry",
        return_value=mock_registry,
    ):
        await broadcast.start_listener()

    assert broadcast._listener_task is mock_task
    mock_registry.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_start_listener_idempotent(
    broadcast: WSBroadcast, mock_pubsub: AsyncMock
) -> None:
    """start_listener is idempotent when already started."""
    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.websocket.ws_broadcast.get_task_registry",
        return_value=mock_registry,
    ):
        await broadcast.start_listener()
        await broadcast.start_listener()

    assert broadcast._listener_task is mock_task
    assert mock_registry.create_task.call_count == 1


@pytest.mark.asyncio
async def test_stop_listener_cancels_task(broadcast: WSBroadcast) -> None:
    """stop_listener cancels the background task."""

    async def _dummy() -> None:
        await asyncio.sleep(0)

    task = asyncio.create_task(_dummy())
    broadcast._listener_task = task

    await broadcast.stop_listener()

    assert task.cancelled()
    assert broadcast._listener_task is None


@pytest.mark.asyncio
async def test_stop_listener_noop_when_not_started(broadcast: WSBroadcast) -> None:
    """stop_listener does nothing when listener was not started."""
    await broadcast.stop_listener()
    assert broadcast._listener_task is None


# ─── publish ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish(broadcast: WSBroadcast, mock_pubsub: AsyncMock) -> None:
    """publish delegates to pubsub.publish."""
    mock_pubsub.publish.return_value = 3
    result = await broadcast.publish({"msg": "hello"})
    assert result == 3
    mock_pubsub.publish.assert_awaited_once_with({"msg": "hello"})


# ─── publish_to_group ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_to_group(broadcast: WSBroadcast, mock_pubsub: AsyncMock) -> None:
    """publish_to_group wraps message with group and delegates to pubsub."""
    mock_pubsub.publish.return_value = 2
    result = await broadcast.publish_to_group("room-1", {"text": "hi"})
    assert result == 2
    mock_pubsub.publish.assert_awaited_once_with(
        {"group": "room-1", "message": {"text": "hi"}}
    )


# ─── group ───────────────────────────────────────────────────────────────────


def test_group_returns_redis_set(
    broadcast: WSBroadcast, mock_redis_set: AsyncMock
) -> None:
    """group returns a RedisSet for the given group name."""
    result = broadcast.group("admins")
    assert result is mock_redis_set


# ─── listener loop behavior ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_listener_loop_forwards_dict_messages(
    broadcast: WSBroadcast, mock_pubsub: AsyncMock
) -> None:
    """Listener loop forwards dict messages to local handler."""
    handler = AsyncMock()
    broadcast.set_local_handler(handler)

    async def _async_gen() -> Any:
        yield {"text": "hello"}
        yield {"text": "world"}

    mock_pubsub.subscribe = _async_gen

    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.websocket.ws_broadcast.get_task_registry",
        return_value=mock_registry,
    ):
        await broadcast.start_listener()

    # Simulate running the loop by calling the coroutine directly
    loop_coro = mock_registry.create_task.call_args[0][0]
    await loop_coro

    assert handler.await_count >= 1


@pytest.mark.asyncio
async def test_listener_loop_skips_non_dict_messages(
    broadcast: WSBroadcast, mock_pubsub: AsyncMock
) -> None:
    """Listener loop skips non-dict messages."""
    handler = AsyncMock()
    broadcast.set_local_handler(handler)

    async def _async_gen() -> Any:
        yield "not-a-dict"

    mock_pubsub.subscribe = _async_gen

    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.websocket.ws_broadcast.get_task_registry",
        return_value=mock_registry,
    ):
        await broadcast.start_listener()

    loop_coro = mock_registry.create_task.call_args[0][0]
    await loop_coro

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_listener_loop_handler_exception_logged(
    broadcast: WSBroadcast, mock_pubsub: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Listener loop logs handler exceptions instead of crashing."""
    handler = AsyncMock()
    handler.side_effect = RuntimeError("boom")
    broadcast.set_local_handler(handler)

    async def _async_gen() -> Any:
        yield {"text": "hello"}

    mock_pubsub.subscribe = _async_gen

    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.websocket.ws_broadcast.get_task_registry",
        return_value=mock_registry,
    ):
        await broadcast.start_listener()

    loop_coro = mock_registry.create_task.call_args[0][0]
    await loop_coro

    assert "WS broadcast handler error" in caplog.text


# ─── singleton ───────────────────────────────────────────────────────────────


def test_ws_broadcast_singleton() -> None:
    """ws_broadcast is a singleton instance."""
    from src.backend.entrypoints.websocket.ws_broadcast import WSBroadcast

    assert isinstance(ws_broadcast, WSBroadcast)
