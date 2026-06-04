"""Unit-тесты windowed dedup processors: WindowedDedupProcessor,
WindowedCollectProcessor.

Паттерн: async tests, моки для Redis через monkeypatch.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.windowed_dedup import (
    WindowedCollectProcessor,
    WindowedDedupProcessor,
    _dedup_batch,
    _extract_path,
    _serialize,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.fixture
def mock_redis(monkeypatch):
    """Мок Redis-клиента с execute(queue, lambda c: ...)."""
    client = AsyncMock()
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.storage.redis.redis_client", client
    )
    return client


# =============================================================================
# Helpers
# =============================================================================


def test_extract_path_nested() -> None:
    assert _extract_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_extract_path_missing() -> None:
    assert _extract_path({"a": 1}, "b.c") is None


def test_extract_path_non_dict() -> None:
    assert _extract_path([1, 2], "a") is None


def test_serialize_roundtrip() -> None:
    assert _serialize({"a": 1}) == '{"a":1}'


def test_dedup_batch_first() -> None:
    items = [{"id": "a", "v": 1}, {"id": "a", "v": 2}, {"id": "b", "v": 3}]
    result = _dedup_batch(items, by="id", mode="first")
    assert result == [{"id": "a", "v": 1}, {"id": "b", "v": 3}]


def test_dedup_batch_last() -> None:
    items = [{"id": "a", "v": 1}, {"id": "a", "v": 2}, {"id": "b", "v": 3}]
    result = _dedup_batch(items, by="id", mode="last")
    assert result == [{"id": "a", "v": 2}, {"id": "b", "v": 3}]


# =============================================================================
# WindowedDedupProcessor
# =============================================================================


def test_dedup_invalid_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        WindowedDedupProcessor(key_from="id", mode="unknown")


@pytest.mark.asyncio
async def test_dedup_first_new_key(mock_redis) -> None:
    """first mode + новый ключ → сообщение проходит (set nx=True)."""
    mock_redis.execute.return_value = True
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="first")
    e = _ex(body={"id": "123", "data": "x"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped
    mock_redis.execute.assert_awaited()


@pytest.mark.asyncio
async def test_dedup_first_duplicate_stops(mock_redis) -> None:
    """first mode + дубль → exchange.stop()."""
    mock_redis.execute.return_value = False
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="first")
    e = _ex(body={"id": "123", "data": "x"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.stopped


@pytest.mark.asyncio
async def test_dedup_last_new_key(mock_redis) -> None:
    """last mode + новый ключ → проходит (nx=True)."""
    mock_redis.execute.return_value = True
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="last")
    e = _ex(body={"id": "123", "data": "x"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped


@pytest.mark.asyncio
async def test_dedup_last_duplicate_updates(mock_redis) -> None:
    """last mode + дубль → обновляет latest и стоп."""
    mock_redis.execute.side_effect = [False, True]  # nx=False, keepttl=True
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="last")
    e = _ex(body={"id": "123", "data": "updated"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.stopped
    assert mock_redis.execute.await_count == 2


@pytest.mark.asyncio
async def test_dedup_unique_new(mock_redis) -> None:
    """unique mode + новый хеш → проходит (sadd=1)."""
    mock_redis.execute.side_effect = [1, True]  # sadd=1, expire ok
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="unique")
    e = _ex(body={"id": "123", "data": "x"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped


@pytest.mark.asyncio
async def test_dedup_unique_duplicate_stops(mock_redis) -> None:
    """unique mode + дубль → стоп (sadd=0)."""
    mock_redis.execute.return_value = 0
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="unique")
    e = _ex(body={"id": "123", "data": "x"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.stopped


@pytest.mark.asyncio
async def test_dedup_empty_key_passes(mock_redis) -> None:
    """Пустой ключ → сообщение проходит без Redis-вызова."""
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="first")
    e = _ex(body={"data": "no-id"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped
    mock_redis.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_redis_error_fallback(mock_redis) -> None:
    """Redis недоступен → сообщение проходит (warning)."""
    mock_redis.execute.side_effect = RuntimeError("redis down")
    proc = WindowedDedupProcessor(key_from="id", window_seconds=10, mode="first")
    e = _ex(body={"id": "123"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped


@pytest.mark.asyncio
async def test_dedup_get_latest(mock_redis) -> None:
    """get_latest возвращает десериализованное значение."""
    mock_redis.execute.return_value = b'{"v": 42}'
    proc = WindowedDedupProcessor(key_from="id", mode="last")
    result = await proc.get_latest("123")
    assert result == {"v": 42}


@pytest.mark.asyncio
async def test_dedup_get_latest_none(mock_redis) -> None:
    """get_latest при отсутствии ключа → None."""
    mock_redis.execute.return_value = None
    proc = WindowedDedupProcessor(key_from="id", mode="last")
    result = await proc.get_latest("123")
    assert result is None


def test_dedup_to_spec() -> None:
    proc = WindowedDedupProcessor(
        key_from="entity.id", key_prefix="orders", window_seconds=120, mode="last"
    )
    assert proc.to_spec() == {
        "windowed_dedup": {
            "key_from": "entity.id",
            "key_prefix": "orders",
            "window_seconds": 120,
            "mode": "last",
        }
    }


# =============================================================================
# WindowedCollectProcessor
# =============================================================================


def test_collect_invalid_dedup_mode() -> None:
    with pytest.raises(ValueError, match="dedup_mode"):
        WindowedCollectProcessor(key_from="id", dedup_by="id", dedup_mode="unknown")


@pytest.mark.asyncio
async def test_collect_first_window_stops(mock_redis) -> None:
    """Первое сообщение (ttl<=0, пустой батч) → стартует окно, стоп."""
    # ttl=-1, lrange=[], delete=1, set=True, rpush=1
    mock_redis.execute.side_effect = [-1, [], 1, True, 1]
    proc = WindowedCollectProcessor(key_from="id", window_seconds=10, dedup_by="id")
    e = _ex(body={"id": "a", "v": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.stopped
    assert e.properties.get("collected_batch") is None


@pytest.mark.asyncio
async def test_collect_active_window_stops(mock_redis) -> None:
    """Сообщение в активном окне → буферизуется и стоп."""
    mock_redis.execute.side_effect = [5, 1]  # ttl=5, rpush ok
    proc = WindowedCollectProcessor(key_from="id", window_seconds=10, dedup_by="id")
    e = _ex(body={"id": "a", "v": 2})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.stopped
    assert e.properties.get("collected_batch") is None


@pytest.mark.asyncio
async def test_collect_window_expired_flushes(mock_redis) -> None:
    """Окно истекло → flush предыдущего батча, инжекция в exchange."""
    # ttl=-1 (окно истекло), lrange returns one item, delete ok, set ok
    raw = b'{"id": "a", "v": 1}'
    mock_redis.execute.side_effect = [
        -1,  # ttl
        [raw],  # lrange
        1,  # delete
        True,  # set win_key
    ]
    proc = WindowedCollectProcessor(key_from="id", window_seconds=10, dedup_by="id")
    e = _ex(body={"id": "a", "v": 2})
    await proc.process(e, None)  # type: ignore[arg-type]

    batch = e.properties.get("collected_batch")
    assert batch is not None
    assert len(batch) == 1
    assert batch[0] == {"id": "a", "v": 1}
    assert not e.stopped


@pytest.mark.asyncio
async def test_collect_get_current_batch(mock_redis) -> None:
    """get_current_batch возвращает дедублицированный батч."""
    raw1 = b'{"id": "a", "v": 1}'
    raw2 = b'{"id": "a", "v": 2}'
    mock_redis.execute.return_value = [raw1, raw2]
    proc = WindowedCollectProcessor(
        key_from="id", window_seconds=10, dedup_by="id", dedup_mode="last"
    )
    result = await proc.get_current_batch("a")
    assert result == [{"id": "a", "v": 2}]


@pytest.mark.asyncio
async def test_collect_redis_error_fallback(mock_redis) -> None:
    """Redis недоступен → сообщение проходит."""
    mock_redis.execute.side_effect = RuntimeError("redis down")
    proc = WindowedCollectProcessor(key_from="id", window_seconds=10, dedup_by="id")
    e = _ex(body={"id": "a", "v": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert not e.stopped


def test_collect_to_spec() -> None:
    proc = WindowedCollectProcessor(
        key_from="entity.id",
        window_seconds=60,
        dedup_by="entity.id",
        dedup_mode="first",
        inject_as="batch",
    )
    assert proc.to_spec() == {
        "windowed_collect": {
            "key_from": "entity.id",
            "dedup_by": "entity.id",
            "window_seconds": 60,
            "dedup_mode": "first",
            "inject_as": "batch",
        }
    }
