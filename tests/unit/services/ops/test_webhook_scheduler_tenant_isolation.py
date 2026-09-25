"""v6 W3.2 contract test — WebhookScheduler tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test. Erasure PASS только если данные tenant A исчезли,
tenant B сохранились».

WebhookScheduler.get() в src/backend/services/ops/webhook_scheduler.py
классифицирован как USER_DATA в W3.1 — после 25.09 audit fix
реализована tenant isolation (ADR-0345 Option A): Redis keys
namespaced per tenant, ``get``/``cancel``/``list_scheduled``/
``execute_webhook`` требуют ``tenant_id`` и фильтруют по namespace.

Контрактные тесты:
- Tenant A schedule — tenant A видит, tenant B НЕ видит (cross-tenant).
- Tenant B schedule — tenant B видит, tenant A НЕ видит.
- list_scheduled фильтрует по tenant.
- cancel cross-tenant → False (не удаляет чужой schedule).
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeRedis:
    """In-memory key-value store с async API (имитация redis.asyncio.Redis)."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    async def scan_iter(self, match: str) -> Any:
        """Async iterator по keys matching prefix."""
        prefix = match.rstrip("*")
        for k in list(self._store.keys()):
            if k.startswith(prefix):
                yield k


@pytest.fixture()
def fake_redis_kv() -> _FakeRedis:
    """Fake redis_kv client для override provider."""
    return _FakeRedis()


@pytest.fixture()
def scheduler(fake_redis_kv, monkeypatch):
    """WebhookScheduler с fake redis подменой."""
    from src.backend.core.di.providers import cache as cache_providers
    from src.backend.services.ops import webhook_scheduler

    cache_providers.set_redis_kv_client_provider(fake_redis_kv)
    yield webhook_scheduler.WebhookScheduler()
    cache_providers.set_redis_kv_client_provider(None)


@pytest.mark.asyncio
async def test_get_returns_none_for_unrelated_schedule(scheduler, fake_redis_kv):
    """Sanity: get(unknown_id) returns None."""
    result = await scheduler.get("nonexistent", tenant_id="tenant_a")
    assert result is None


@pytest.mark.asyncio
async def test_cross_tenant_get_returns_none(scheduler):
    """Tenant A schedule — tenant B get() возвращает None (negative test)."""
    # Tenant A schedules webhook.
    schedule_id = await scheduler.schedule(
        url="https://example.com/webhook",
        payload={"event": "order.created"},
        cron="0 * * * *",
        tenant_id="tenant_a",
    )

    # Tenant A видит свой schedule.
    own = await scheduler.get(schedule_id, tenant_id="tenant_a")
    assert own is not None
    assert own["id"] == schedule_id
    assert own["tenant_id"] == "tenant_a"

    # Tenant B НЕ видит tenant A's schedule.
    cross = await scheduler.get(schedule_id, tenant_id="tenant_b")
    assert cross is None, (
        f"TENANT_ISOLATION_FAILED: WebhookScheduler.get cross-tenant "
        f"returned {cross} instead of None. schedule_id={schedule_id}"
    )


@pytest.mark.asyncio
async def test_list_scheduled_filters_by_tenant(scheduler):
    """list_scheduled возвращает только schedules своего tenant."""
    sid_a = await scheduler.schedule(
        url="https://a.example.com",
        payload={"x": 1},
        cron="0 * * * *",
        tenant_id="tenant_a",
    )
    sid_b = await scheduler.schedule(
        url="https://b.example.com",
        payload={"x": 2},
        cron="0 * * * *",
        tenant_id="tenant_b",
    )

    list_a = await scheduler.list_scheduled(tenant_id="tenant_a")
    list_b = await scheduler.list_scheduled(tenant_id="tenant_b")

    ids_a = [t["id"] for t in list_a]
    ids_b = [t["id"] for t in list_b]

    assert sid_a in ids_a
    assert sid_a not in ids_b
    assert sid_b in ids_b
    assert sid_b not in ids_a


@pytest.mark.asyncio
async def test_cross_tenant_cancel_returns_false(scheduler):
    """Tenant B cancel tenant A's schedule → False (не удаляет чужой)."""
    sid = await scheduler.schedule(
        url="https://a.example.com",
        payload={"x": 1},
        cron="0 * * * *",
        tenant_id="tenant_a",
    )

    # Tenant B пытается отменить tenant A's schedule.
    cancelled = await scheduler.cancel(sid, tenant_id="tenant_b")
    assert cancelled is False

    # Tenant A всё ещё видит свой schedule.
    still = await scheduler.get(sid, tenant_id="tenant_a")
    assert still is not None
    assert still["id"] == sid

    # Tenant A успешно отменяет свой schedule.
    cancelled_own = await scheduler.cancel(sid, tenant_id="tenant_a")
    assert cancelled_own is True

    gone = await scheduler.get(sid, tenant_id="tenant_a")
    assert gone is None


@pytest.mark.asyncio
async def test_execute_webhook_cross_tenant_returns_not_found(scheduler):
    """execute_webhook cross-tenant → {"error": "not_found"} (не выполняет чужой)."""
    sid = await scheduler.schedule(
        url="https://a.example.com/webhook",
        payload={"x": 1},
        cron="0 * * * *",
        tenant_id="tenant_a",
    )

    # Tenant B пытается выполнить tenant A's webhook.
    result = await scheduler.execute_webhook(sid, tenant_id="tenant_b")
    assert result == {"error": "not_found"}, (
        f"TENANT_ISOLATION_FAILED: execute_webhook cross-tenant returned "
        f"{result} instead of not_found. Tenant B смог execute чужой webhook!"
    )


@pytest.mark.asyncio
async def test_redis_key_includes_tenant_id(scheduler, fake_redis_kv):
    """Redis key содержит tenant_id в namespace (audit trail)."""
    sid = await scheduler.schedule(
        url="https://example.com",
        payload={"x": 1},
        cron="0 * * * *",
        tenant_id="acme_corp",
    )
    expected_key = "webhook:scheduled:acme_corp:" + sid
    assert expected_key in fake_redis_kv._store, (
        f"TENANT_NAMESPACE_FAILED: expected key {expected_key!r} not found "
        f"in Redis. Found keys: {list(fake_redis_kv._store.keys())}"
    )
