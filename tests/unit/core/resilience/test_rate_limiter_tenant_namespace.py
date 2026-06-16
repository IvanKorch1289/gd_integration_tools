"""Тесты per-tenant namespace для rate-limiter (Sprint 8A K2 W7).

Проверяет:
- ``RateLimit.tenant_aware`` дефолтит в False (backward-compat).
- При ``tenant_aware=True`` ключ Redis получает префикс ``tenant:<id>``.
- Изоляция счётчиков между двумя тенантами.
- Fallback ``tenant:_default_`` если контекст не установлен.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.resilience.rate_limiter import RateLimit, RateLimitExceeded
from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.infrastructure.resilience import unified_rate_limiter
from src.backend.infrastructure.resilience.unified_rate_limiter import (
    RedisRateLimiter,
    _resolve_tenant_segment,
)


class _FakePipe:
    def __init__(self, store: dict[str, int]):
        self._store = store
        self._ops: list[tuple[str, str, int]] = []

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key, 0))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    async def execute(self) -> list[int]:
        results: list[int] = []
        for op, key, _ttl in self._ops:
            if op == "incr":
                self._store[key] = self._store.get(key, 0) + 1
                results.append(self._store[key])
        return results


class _FakeRedis:
    """Минимальный fake для unified_rate_limiter (INCR/EXPIRE через pipeline)."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.keys_seen: list[str] = []

    def pipeline(self) -> _FakePipe:
        return _FakePipe(self.store)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Подменяет ``get_redis_client`` на in-memory fake для unified_rate_limiter.

    Production code (unified_rate_limiter.py:94) делает
    ``from ... import get_redis_client as redis_client``, поэтому нужно
    patchить функцию get_redis_client чтобы она возвращала fake-instance.
    """
    fake = _FakeRedis()
    import src.backend.infrastructure.clients.storage.redis as redis_mod
    monkeypatch.setattr(redis_mod, "get_redis_client", lambda: fake)
    yield fake


def test_rate_limit_tenant_aware_defaults_false() -> None:
    """Backward-compat: ``tenant_aware`` дефолтит в False."""
    policy = RateLimit(limit=10, window_seconds=60)
    assert policy.tenant_aware is False


def test_rate_limit_tenant_aware_opt_in() -> None:
    """Явно опт-ин через field."""
    policy = RateLimit(limit=10, window_seconds=60, tenant_aware=True)
    assert policy.tenant_aware is True


def test_resolve_tenant_segment_default_without_context() -> None:
    """Без контекста — fallback ``tenant:_default_``."""
    assert _resolve_tenant_segment() == "tenant:_default_"


def test_resolve_tenant_segment_with_context() -> None:
    """С активным TenantContext — ``tenant:<id>``."""
    ctx = TenantContext(tenant_id="acme")
    with tenant_scope(ctx):
        assert _resolve_tenant_segment() == "tenant:acme"
    # после выхода — снова default
    assert _resolve_tenant_segment() == "tenant:_default_"


def test_rate_limit_key_without_tenant_namespace(fake_redis: _FakeRedis) -> None:
    """``tenant_aware=False`` — ключ без сегмента tenant."""
    limiter = RedisRateLimiter()
    policy = RateLimit(limit=100, window_seconds=60, key_prefix="rl")
    asyncio.run(limiter.check("user-1", policy))
    # ключ вида "rl:user-1:<window_start>", без "tenant:"
    keys = list(fake_redis.store.keys())
    assert len(keys) == 1
    assert "tenant:" not in keys[0]
    assert keys[0].startswith("rl:user-1:")


def test_rate_limit_key_with_tenant_namespace(fake_redis: _FakeRedis) -> None:
    """``tenant_aware=True`` + контекст — ключ с ``tenant:<id>``."""
    limiter = RedisRateLimiter()
    policy = RateLimit(limit=100, window_seconds=60, key_prefix="rl", tenant_aware=True)
    with tenant_scope(TenantContext(tenant_id="acme")):
        asyncio.run(limiter.check("user-1", policy))
    keys = list(fake_redis.store.keys())
    assert len(keys) == 1
    assert keys[0].startswith("rl:tenant:acme:user-1:")


def test_rate_limit_isolation_between_tenants(fake_redis: _FakeRedis) -> None:
    """Два тенанта с одинаковым identifier не делят счётчик."""
    limiter = RedisRateLimiter()
    policy = RateLimit(limit=5, window_seconds=60, key_prefix="rl", tenant_aware=True)

    async def hit_for(tenant: str, times: int) -> None:
        with tenant_scope(TenantContext(tenant_id=tenant)):
            for _ in range(times):
                await limiter.check("shared-id", policy)

    asyncio.run(hit_for("acme", 3))
    asyncio.run(hit_for("globex", 4))

    # 2 разных ключа (по одному на тенанта), каждый со своим counter'ом
    acme_keys = [k for k in fake_redis.store if "tenant:acme" in k]
    globex_keys = [k for k in fake_redis.store if "tenant:globex" in k]
    assert len(acme_keys) == 1
    assert len(globex_keys) == 1
    assert fake_redis.store[acme_keys[0]] == 3
    assert fake_redis.store[globex_keys[0]] == 4


def test_rate_limit_exceeded_per_tenant(fake_redis: _FakeRedis) -> None:
    """``RateLimitExceeded`` бросается per-tenant, не глобально."""
    limiter = RedisRateLimiter()
    policy = RateLimit(limit=2, window_seconds=60, key_prefix="rl", tenant_aware=True)

    async def scenario() -> None:
        # acme: 2 ok, 3-й бросает
        with tenant_scope(TenantContext(tenant_id="acme")):
            await limiter.check("u", policy)
            await limiter.check("u", policy)
            with pytest.raises(RateLimitExceeded):
                await limiter.check("u", policy)
        # globex изолирован — может делать свои 2
        with tenant_scope(TenantContext(tenant_id="globex")):
            await limiter.check("u", policy)
            await limiter.check("u", policy)

    asyncio.run(scenario())


def test_fallback_to_default_when_no_context(fake_redis: _FakeRedis) -> None:
    """``tenant_aware=True`` без активного контекста — namespace ``_default_``."""
    limiter = RedisRateLimiter()
    policy = RateLimit(limit=10, window_seconds=60, key_prefix="rl", tenant_aware=True)
    asyncio.run(limiter.check("anon-1", policy))
    keys = list(fake_redis.store.keys())
    assert len(keys) == 1
    assert "tenant:_default_" in keys[0]


def test_module_export_includes_dataclass_field() -> None:
    """``_resolve_tenant_segment`` выставлен в module для тестируемости."""
    assert hasattr(unified_rate_limiter, "_resolve_tenant_segment")
