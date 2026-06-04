"""Unit-тесты RedisBreakerStateStorage — ``[wave:s18/w0-goal-driven-sweep-4-redis-breaker-storage]``.

Использует минимальный async-Redis mock (``_DictRedis``), чтобы тесты
работали без зависимости от ``fakeredis``.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import Any

import pytest

from src.backend.core.utils.pybreaker_adapter import (
    BreakerState,
    InMemoryPybreakerAdapter,
)
from src.backend.infrastructure.resilience.redis_breaker_storage import (
    RedisBreakerStateStorage,
)


class _DictRedis:
    """Минимальный async Redis-mock — ``get``/``set``."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.set_calls: list[tuple[str, bytes, int | None]] = []
        self.get_calls: list[str] = []
        # Симулируется только при выставлении флага.
        self.fail_next_set: bool = False
        self.fail_next_get: bool = False

    async def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        if self.fail_next_get:
            self.fail_next_get = False
            raise ConnectionError("redis down")
        return self._data.get(key)

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, **_: Any
    ) -> bool:
        if self.fail_next_set:
            self.fail_next_set = False
            raise ConnectionError("redis down")
        payload = value if isinstance(value, bytes) else value.encode()
        self._data[key] = payload
        self.set_calls.append((key, payload, ex))
        return True


@pytest.mark.asyncio
async def test_save_writes_json_payload() -> None:
    """save() сериализует BreakerState в JSON и пишет в ключ cb:state:{name}."""
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis)
    state = BreakerState(
        name="payments",
        state="open",
        fail_counter=4,
        last_failure_at_iso="2026-05-25T10:00:00+00:00",
    )

    await storage.save(state)

    assert "cb:state:payments" in redis._data
    payload = json.loads(redis._data["cb:state:payments"].decode())
    assert payload == {
        "state": "open",
        "fail_counter": 4,
        "last_failure_at_iso": "2026-05-25T10:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_save_with_ttl_uses_ex() -> None:
    """ttl_seconds прокидывается в redis.set(ex=...)."""
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis, ttl_seconds=3600)
    state = BreakerState(
        name="t", state="closed", fail_counter=0, last_failure_at_iso=""
    )
    await storage.save(state)
    assert redis.set_calls[-1][2] == 3600


@pytest.mark.asyncio
async def test_load_returns_none_for_missing_key() -> None:
    """Когда ключа нет — load() возвращает None."""
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis)
    result = await storage.load("absent")
    assert result is None


@pytest.mark.asyncio
async def test_load_round_trips_state() -> None:
    """save → load возвращает идентичный BreakerState."""
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis)
    original = BreakerState(
        name="inventory",
        state="half_open",
        fail_counter=2,
        last_failure_at_iso="2026-05-25T11:30:00+00:00",
    )
    await storage.save(original)
    loaded = await storage.load("inventory")
    assert loaded == original


@pytest.mark.asyncio
async def test_load_handles_corrupted_payload() -> None:
    """При invalid JSON — load() возвращает None и не падает."""
    redis = _DictRedis()
    redis._data["cb:state:bad"] = b"not-a-json"
    storage = RedisBreakerStateStorage(redis)
    assert await storage.load("bad") is None


@pytest.mark.asyncio
async def test_save_swallows_redis_error() -> None:
    """Если Redis недоступен — save() логирует и не пробрасывает исключение."""
    redis = _DictRedis()
    redis.fail_next_set = True
    storage = RedisBreakerStateStorage(redis)
    state = BreakerState(name="t", state="open", fail_counter=1, last_failure_at_iso="")
    await storage.save(state)  # не должно бросать
    assert redis.set_calls == []  # mock не записал из-за исключения


@pytest.mark.asyncio
async def test_load_swallows_redis_error() -> None:
    """Если Redis даёт ошибку чтения — load() возвращает None."""
    redis = _DictRedis()
    redis.fail_next_get = True
    storage = RedisBreakerStateStorage(redis)
    assert await storage.load("anything") is None


@pytest.mark.asyncio
async def test_key_prefix_override() -> None:
    """Кастомный key_prefix меняет ключ в Redis."""
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis, key_prefix="myapp:cb:")
    state = BreakerState(
        name="api", state="closed", fail_counter=0, last_failure_at_iso=""
    )
    await storage.save(state)
    assert "myapp:cb:api" in redis._data
    assert "cb:state:api" not in redis._data


@pytest.mark.asyncio
async def test_dod9_restart_acceptance_via_inmemory_adapter() -> None:
    """DoD-9 acceptance: открытый breaker восстанавливается из Redis после "рестарта".

    1. Создаём adapter1 с RedisBreakerStateStorage; ждём fail_max отказов → open.
    2. Создаём adapter2 (имитация рестарта) — новый объект, тот же storage.
    3. После restore() adapter2.state == open.
    """
    redis = _DictRedis()
    storage = RedisBreakerStateStorage(redis)

    adapter1 = InMemoryPybreakerAdapter(name="rest", fail_max=2, storage=storage)

    async def bad() -> None:
        raise IOError("upstream")

    with pytest.raises(IOError):
        await adapter1.call(bad)
    with pytest.raises(IOError):
        await adapter1.call(bad)
    assert adapter1.state == "open"

    # «Рестарт»: новый объект, тот же storage.
    adapter2 = InMemoryPybreakerAdapter(name="rest", fail_max=2, storage=storage)
    assert adapter2.state == "closed"  # до restore — defaults
    await adapter2.restore()
    assert adapter2.state == "open"
    assert adapter2.failure_count == 2
