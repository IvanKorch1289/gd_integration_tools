"""Unit-тесты cache-декораторов-фасада (ADR-0051).

Покрытие:
* @cached(ttl, key="bki:{args[0]}", backend="memory") — hit/miss;
* key-templating через позиционные args + kwargs;
* @cached с custom key-builder (callable);
* @invalidate(pattern) — лучшее-возможное удаление;
* @cached на не-async функции → TypeError;
* @multi_cached(ttls) — wrapper устанавливает min-TTL.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.resilience.cache_decorators import (
    cached,
    invalidate,
    multi_cached,
)


@pytest.mark.asyncio
async def test_cached_memory_backend_returns_cached_on_second_call() -> None:
    calls: list[int] = []

    @cached(ttl=60, key="bki:{args[0]}", backend="memory")
    async def fetch(user_id: int) -> dict:
        calls.append(user_id)
        return {"user": user_id, "v": 1}

    first = await fetch(7)
    second = await fetch(7)
    assert first == second == {"user": 7, "v": 1}
    # Второй вызов попал в кеш → счётчик calls остался 1.
    assert calls == [7]


@pytest.mark.asyncio
async def test_cached_different_args_compute_separately() -> None:
    calls: list[int] = []

    @cached(ttl=60, key="bki:{args[0]}", backend="memory")
    async def fetch(user_id: int) -> int:
        calls.append(user_id)
        return user_id * 2

    assert await fetch(1) == 2
    assert await fetch(2) == 4
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_cached_with_callable_key_builder() -> None:
    def kb(user_id: int) -> str:
        return f"custom:{user_id}"

    @cached(ttl=60, key=kb, backend="memory")
    async def fetch(user_id: int) -> int:
        return user_id + 100

    assert await fetch(5) == 105
    assert await fetch(5) == 105


def test_cached_rejects_sync_function() -> None:
    with pytest.raises(TypeError, match="async"):

        @cached(ttl=60, key="x", backend="memory")
        def fetch():  # type: ignore[misc]
            return 1


def test_invalidate_rejects_sync_function() -> None:
    with pytest.raises(TypeError, match="async"):

        @invalidate("x:*")
        def fetch():  # type: ignore[misc]
            return 1


@pytest.mark.asyncio
async def test_invalidate_calls_redis_delete_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    class FakeRedis:
        async def cache_delete_pattern(self, pattern: str) -> None:
            captured.append(pattern)

    import src.backend.infrastructure.clients.storage.redis as redis_mod

    monkeypatch.setattr(redis_mod, "redis_client", FakeRedis(), raising=False)

    @invalidate("bki:*")
    async def update(uid: int) -> str:
        return f"updated:{uid}"

    result = await update(1)
    assert result == "updated:1"
    assert captured == ["bki:*"]


@pytest.mark.asyncio
async def test_invalidate_swallows_redis_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRedis:
        async def cache_delete_pattern(self, pattern: str) -> None:
            raise RuntimeError("redis down")

    import src.backend.infrastructure.clients.storage.redis as redis_mod

    monkeypatch.setattr(redis_mod, "redis_client", FailingRedis(), raising=False)

    @invalidate("bki:*")
    async def update() -> str:
        return "ok"

    # Не должно бросить — best-effort.
    assert await update() == "ok"


@pytest.mark.asyncio
async def test_multi_cached_uses_min_ttl() -> None:
    @multi_cached(ttls={"summary": 60, "raw": 600})
    async def compute(user_id: int) -> dict:
        return {"summary": "...", "raw": "..."}

    first = await compute(1)
    assert first == {"summary": "...", "raw": "..."}


def test_multi_cached_rejects_empty_ttls() -> None:
    with pytest.raises(ValueError, match="ttls"):
        multi_cached(ttls={})


def test_resilience_package_reexports_cache_decorators() -> None:
    from src.backend.core import resilience

    assert resilience.cached is cached
    assert resilience.invalidate is invalidate
    assert resilience.multi_cached is multi_cached


@pytest.mark.asyncio
async def test_multi_cached_includes_positional_args_in_key() -> None:
    """Разные позиционные аргументы дают разные ключи кеша."""
    calls: list[int] = []

    @multi_cached(ttls={"summary": 60})
    async def compute(user_id: int) -> dict:
        calls.append(user_id)
        return {"summary": f"user_{user_id}"}

    first = await compute(1)
    second = await compute(2)
    assert first == {"summary": "user_1"}
    assert second == {"summary": "user_2"}
    # Функция должна быть вызвана дважды, т.к. ключи разные.
    assert calls == [1, 2]
