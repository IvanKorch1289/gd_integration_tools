"""v6 W3.2 contract test — WebhookScheduler tenant isolation (negative).

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test. Erasure PASS только если данные tenant A исчезли,
tenant B сохранились».

WebhookScheduler.get() в src/backend/services/ops/webhook_scheduler.py:94
был классифицирован как USER_DATA в W3.1 — нет tenant filter
на Redis lookup. Per ADR-0345 Option A требуется tenant predicate.

Этот тест ДОКУМЕНТИРУЕТ gap (как debt) — не fix.
Negative test FAILING = current code lacks tenant isolation (real P0).
Per v6 §3: «расхождение runtime != architecture фиксируй как debt,
а не «исправляй» молча».
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
    """Sanity: get(unknown_id) returns None.

    Baseline — поведение корректное когда schedule не существует.
    """
    result = await scheduler.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_schedule_without_tenant_context(scheduler):
    """Per W3.1 classification: WebhookScheduler.get НЕ фильтрует по tenant.

    Этот тест документирует существующее поведение: schedule создан
    с schedule_id доступен любому caller'у (НЕ tenant-scoped).

    Per v6 W3.2: negative cross-tenant test ДОЛЖЕН провалиться —
    чтобы зафиксировать debt для будущего fix.
    """
    # Tenant A schedules webhook.
    schedule_id = await scheduler.schedule(
        url="https://example.com/webhook",
        payload={"event": "order.created"},
        cron="0 * * * *",
    )

    # Simulate tenant B context (different caller) attempting to read
    # tenant A's webhook. Per v6 W3.2: SHOULD return None (tenant filter).
    # Current behavior (BUG): returns the schedule regardless of caller.
    result = await scheduler.get(schedule_id)

    # Current (incorrect) behavior: returns schedule.
    # After tenant-isolation fix: should be None (tenant filter).
    # This test asserts the DESIRED behavior — will FAIL until fix.
    assert result is None, (
        f"TENANT_ISOLATION_DEBT: WebhookScheduler.get(schedule_id) returned "
        f"schedule from tenant A without tenant filter. schedule_id={schedule_id}, "
        f"result={result}. Per v6 §10 W3 + ADR-0345 Option A: должен быть "
        f"tenant predicate filter. See docs/roadmap/W3_UNKNOWN_OWNERSHIP_"
        f"CLASSIFICATION_2026-09-24.md раздел 2.1."
    )
