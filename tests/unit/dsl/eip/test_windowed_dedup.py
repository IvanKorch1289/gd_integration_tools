"""Unit-тесты WindowedDedupProcessor + WindowedCollectProcessor (Wave 18.U3).

Покрытие:
    * mode=first   — первое сообщение в окне проходит, дубль — стоп.
    * mode=last    — первое проходит, последующие обновляют latest и стоп.
    * mode=unique  — дубль по содержимому — стоп; иной body — проходит.
    * Пустой ключ → сообщение проходит без обращения к Redis.
    * Redis-фейл → сообщение проходит (graceful degradation).
    * to_spec() round-trip.
    * WindowedCollectProcessor: lazy-flush и буферизация.

Redis-клиент полностью замокан через AsyncMock — реальный Redis не нужен.
"""
# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.windowed_dedup import (
    WindowedCollectProcessor,
    WindowedDedupProcessor,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_exchange(body: Any) -> Exchange:
    """Создаёт минимальный Exchange с указанным body."""
    return Exchange(in_message=Message(body=body))


def _make_context() -> ExecutionContext:
    """Минимальный ExecutionContext."""
    return ExecutionContext(route_id="dedup-test")


class _FakeRedisClient:
    """Простая in-memory имитация интерфейса ``redis_client.execute(kind, op)``.

    Поддерживает минимальный набор операций: ``set``, ``get``, ``sadd``,
    ``expire``, ``ttl``, ``rpush``, ``lrange``, ``delete``.
    """

    def __init__(self) -> None:
        self.kv: dict[str, Any] = {}
        self.sets: dict[str, set[Any]] = {}
        self.lists: dict[str, list[Any]] = {}
        self.ttl: dict[str, int] = {}

    async def execute(self, kind: str, operation):  # noqa: ARG002
        return await operation(_FakeRedisProxy(self))


class _FakeRedisProxy:
    """Прокси, реализующий sync-API redis-py для FakeRedis state."""

    def __init__(self, store: _FakeRedisClient) -> None:
        self._s = store

    async def set(  # noqa: A003
        self,
        key: str,
        value: Any,
        *,
        nx: bool = False,
        ex: int | None = None,
        keepttl: bool = False,
    ) -> bool:
        if nx and key in self._s.kv:
            return False
        self._s.kv[key] = value
        if ex is not None:
            self._s.ttl[key] = ex
        elif not keepttl:
            self._s.ttl.pop(key, None)
        return True

    async def get(self, key: str) -> Any | None:
        return self._s.kv.get(key)

    async def sadd(self, key: str, member: Any) -> int:
        s = self._s.sets.setdefault(key, set())
        if member in s:
            return 0
        s.add(member)
        return 1

    async def expire(self, key: str, seconds: int) -> int:
        if key in self._s.kv or key in self._s.sets or key in self._s.lists:
            self._s.ttl[key] = seconds
            return 1
        return 0

    async def ttl(self, key: str) -> int:
        return self._s.ttl.get(key, -2)

    async def rpush(self, key: str, value: Any) -> int:
        lst = self._s.lists.setdefault(key, [])
        lst.append(value)
        return len(lst)

    async def lrange(self, key: str, start: int, stop: int) -> list[Any]:
        lst = self._s.lists.get(key, [])
        if stop == -1:
            return list(lst[start:])
        return list(lst[start : stop + 1])

    async def delete(self, key: str) -> int:
        removed = 0
        for store in (self._s.kv, self._s.sets, self._s.lists):
            if key in store:
                store.pop(key, None)
                removed += 1
        self._s.ttl.pop(key, None)
        return removed


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedisClient:
    """Подменяет ``src.infrastructure.clients.storage.redis.redis_client``."""
    fake = _FakeRedisClient()
    fake_module = types.ModuleType("src.backend.infrastructure.clients.storage.redis")
    setattr(fake_module, "redis_client", fake)
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.clients.storage.redis", fake_module
    )
    return fake


# ---------------------------------------------------------------------------
# mode=first
# ---------------------------------------------------------------------------


async def test_mode_first_passes_first_message(fake_redis: _FakeRedisClient) -> None:
    """mode=first: первое сообщение в окне проходит без stop()."""
    proc = WindowedDedupProcessor(key_from="entity_id", mode="first")
    ex = _make_exchange({"entity_id": "k1", "v": 1})
    await proc.process(ex, _make_context())
    assert ex.stopped is False


async def test_mode_first_blocks_duplicate(fake_redis: _FakeRedisClient) -> None:
    """mode=first: повтор того же ключа в окне останавливается."""
    proc = WindowedDedupProcessor(key_from="entity_id", mode="first")
    first = _make_exchange({"entity_id": "k1"})
    await proc.process(first, _make_context())
    second = _make_exchange({"entity_id": "k1"})
    await proc.process(second, _make_context())
    assert second.stopped is True


# ---------------------------------------------------------------------------
# mode=last
# ---------------------------------------------------------------------------


async def test_mode_last_first_passes_subsequent_stops_and_updates_latest(
    fake_redis: _FakeRedisClient,
) -> None:
    """mode=last: первое сообщение проходит; последующие обновляют latest и stop."""
    proc = WindowedDedupProcessor(key_from="id", mode="last", key_prefix="orders")
    ex1 = _make_exchange({"id": "x", "v": 1})
    await proc.process(ex1, _make_context())
    assert ex1.stopped is False

    ex2 = _make_exchange({"id": "x", "v": 2})
    await proc.process(ex2, _make_context())
    assert ex2.stopped is True

    latest = await proc.get_latest("x")
    assert latest == {"id": "x", "v": 2}


# ---------------------------------------------------------------------------
# mode=unique
# ---------------------------------------------------------------------------


async def test_mode_unique_blocks_exact_duplicate(
    fake_redis: _FakeRedisClient,
) -> None:
    """mode=unique: точный дубль body — stop; иной body — проходит."""
    proc = WindowedDedupProcessor(key_from="id", mode="unique")

    ex1 = _make_exchange({"id": "k", "v": 1})
    await proc.process(ex1, _make_context())
    assert ex1.stopped is False

    # Точный дубль — stop
    ex2 = _make_exchange({"id": "k", "v": 1})
    await proc.process(ex2, _make_context())
    assert ex2.stopped is True

    # Иной body, но тот же ключ — проходит (новый hash в SET)
    ex3 = _make_exchange({"id": "k", "v": 2})
    await proc.process(ex3, _make_context())
    assert ex3.stopped is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_empty_key_passes_without_redis(fake_redis: _FakeRedisClient) -> None:
    """Пустой ключ → сообщение проходит, redis не дёргается."""
    proc = WindowedDedupProcessor(key_from="missing.key", mode="first")
    ex = _make_exchange({"a": 1})
    await proc.process(ex, _make_context())
    assert ex.stopped is False
    # Никаких записей в redis не появилось
    assert fake_redis.kv == {}


async def test_redis_failure_passes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если Redis-вызов бросает исключение — сообщение проходит (graceful)."""
    failing = AsyncMock(side_effect=RuntimeError("redis down"))
    fake_module = types.ModuleType("src.backend.infrastructure.clients.storage.redis")
    setattr(fake_module, "redis_client", types.SimpleNamespace(execute=failing))
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.clients.storage.redis", fake_module
    )

    proc = WindowedDedupProcessor(key_from="id", mode="first")
    ex = _make_exchange({"id": "x"})
    await proc.process(ex, _make_context())
    assert ex.stopped is False  # graceful pass-through


def test_invalid_mode_raises() -> None:
    """Неверный mode → ValueError на этапе конструктора."""
    with pytest.raises(ValueError, match="mode="):
        WindowedDedupProcessor(key_from="id", mode="weird")


# ---------------------------------------------------------------------------
# to_spec / round-trip
# ---------------------------------------------------------------------------


def test_to_spec_dedup() -> None:
    """to_spec возвращает все 4 поля для round-trip."""
    proc = WindowedDedupProcessor(
        key_from="body.id", key_prefix="my", window_seconds=120, mode="last"
    )
    assert proc.to_spec() == {
        "windowed_dedup": {
            "key_from": "body.id",
            "key_prefix": "my",
            "window_seconds": 120,
            "mode": "last",
        }
    }


def test_to_spec_collect() -> None:
    """WindowedCollectProcessor.to_spec для round-trip."""
    proc = WindowedCollectProcessor(
        key_from="body.table",
        dedup_by="body.id",
        window_seconds=30,
        dedup_mode="first",
        inject_as="batch",
    )
    assert proc.to_spec() == {
        "windowed_collect": {
            "key_from": "body.table",
            "dedup_by": "body.id",
            "window_seconds": 30,
            "dedup_mode": "first",
            "inject_as": "batch",
        }
    }


def test_collect_invalid_dedup_mode_raises() -> None:
    """WindowedCollectProcessor: неверный dedup_mode → ValueError."""
    with pytest.raises(ValueError, match="dedup_mode"):
        WindowedCollectProcessor(key_from="t", dedup_by="id", dedup_mode="bogus")


# ---------------------------------------------------------------------------
# WindowedCollectProcessor — поведение lazy-flush
# ---------------------------------------------------------------------------


async def test_collect_first_message_buffers_and_stops(
    fake_redis: _FakeRedisClient,
) -> None:
    """Первое сообщение нового окна — буферизуется и stop()."""
    proc = WindowedCollectProcessor(
        key_from="table",
        dedup_by="id",
        window_seconds=60,
        dedup_mode="last",
        inject_as="batch",
    )
    ex = _make_exchange({"table": "orders", "id": "1", "v": 1})
    await proc.process(ex, _make_context())
    assert ex.stopped is True


async def test_collect_within_active_window_buffers_and_stops(
    fake_redis: _FakeRedisClient,
) -> None:
    """В рамках активного окна каждое сообщение buf+stop, не инжектируется."""
    proc = WindowedCollectProcessor(
        key_from="table",
        dedup_by="id",
        window_seconds=60,
        dedup_mode="last",
        inject_as="batch",
    )

    ex1 = _make_exchange({"table": "orders", "id": "1", "v": 1})
    await proc.process(ex1, _make_context())  # стартует окно (lazy-flush пустой батч)

    ex2 = _make_exchange({"table": "orders", "id": "1", "v": 2})
    await proc.process(ex2, _make_context())
    assert ex2.stopped is True
    assert ex2.get_property("batch") is None  # внутри окна — не инжектируется
