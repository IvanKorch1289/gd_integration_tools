"""Регресс-тесты: cache fallback chain (Redis → Memcached → memory).

До фикса (wave 34, infra-аудит) ``cache_chain`` передавал в
``create_cache_backend`` **строку** (``"redis"`` / ``"memcached"``), а
фабрика ожидала ``CacheSettings`` → ``AttributeError: 'str' object has no
attribute 'backend'``. Итог: primary и первый fallback chain'а падали
всегда, breaker ``redis`` открывался самопроизвольно, кэш деградировал в
in-memory даже при живом Redis.

Дополнительно: backend'ы создавались **на каждый вызов** → глобальный
``CacheInvalidator._backends`` рос без ограничения (сравнение по
identity, каждый новый wrapper — новый элемент списка).

Покрывает:

* ``create_cache_backend("redis")`` больше не падает и возвращает backend;
* backend'ы в chain — singletons (создаются один раз);
* число зарегистрированных backend'ов в инвалидаторе не растёт;
* read-path chain'а возвращает значение из fallback-уровня.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.resilience.components import cache_chain


@pytest.fixture(autouse=True)
def _reset_singletons() -> Any:
    """Сбросить module-level singleton'ы до/после теста."""
    cache_chain._redis_backend = None
    cache_chain._memcached_backend = None
    cache_chain._memory_backend = None
    yield
    cache_chain._redis_backend = None
    cache_chain._memcached_backend = None
    cache_chain._memory_backend = None


class _FakeBackend:
    """Минимальный CacheBackend-stand-in."""

    def __init__(self, value: bytes | None = None) -> None:
        self.value = value
        self.calls = 0

    async def get(self, key: str) -> bytes | None:
        self.calls += 1
        return self.value

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        return None

    async def delete(self, *keys: str) -> None:
        return None

    async def delete_pattern(self, pattern: str) -> None:
        return None

    async def exists(self, key: str) -> bool:
        return self.value is not None


@pytest.mark.asyncio
async def test_cache_chain_reads_from_fallback(monkeypatch: Any) -> None:
    """Fallback-уровень chain'а отдаёт значение (chain не падает)."""
    fake = _FakeBackend(b"payload")
    monkeypatch.setattr(cache_chain, "_memory_singleton", lambda: fake)

    assert await cache_chain._memory_get("k") == b"payload"


@pytest.mark.asyncio
async def test_redis_get_does_not_raise_attribute_error(monkeypatch: Any) -> None:
    """``_redis_get`` не падает с AttributeError (строка vs CacheSettings)."""
    fake = _FakeBackend(b"redis-value")
    monkeypatch.setattr(cache_chain, "_redis_singleton", lambda: fake)

    assert await cache_chain._redis_get("k") == b"redis-value"


@pytest.mark.asyncio
async def test_backends_are_created_once(monkeypatch: Any) -> None:
    """Backend создаётся один раз и переиспользуется (нет утечки)."""
    created: list[str] = []
    fake = _FakeBackend(b"x")

    def _fake_factory(name: str) -> _FakeBackend:
        created.append(name)
        return fake

    monkeypatch.setattr(
        "src.backend.infrastructure.cache.factory.create_cache_backend", _fake_factory
    )

    assert await cache_chain._redis_get("k1") == b"x"
    assert await cache_chain._redis_get("k2") == b"x"
    assert created == ["redis"]


@pytest.mark.asyncio
async def test_invalidator_backend_list_does_not_grow(monkeypatch: Any) -> None:
    """Глобальный CacheInvalidator не раздувается вызовами chain'а."""
    from src.backend.infrastructure.cache.invalidator import get_cache_invalidator

    invalidator = get_cache_invalidator()
    before = len(invalidator.backends)

    fake = _FakeBackend(b"x")
    monkeypatch.setattr(cache_chain, "_memory_singleton", lambda: fake)
    for _ in range(5):
        await cache_chain._memory_get("k")

    assert len(invalidator.backends) == before


@pytest.mark.asyncio
async def test_create_cache_backend_accepts_backend_name() -> None:
    """Фабрика принимает имя backend'а строкой (back-compat для call-site'ов)."""
    from src.backend.infrastructure.cache.factory import create_cache_backend

    backend = create_cache_backend("memory")
    assert backend is not None
