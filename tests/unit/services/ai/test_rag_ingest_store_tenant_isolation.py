"""v6 W3.2 contract test — RedisIngestStateStore tenant isolation (negative).

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

RedisIngestStateStore.get(task_id) в src/backend/services/ai/
rag_ingest_store.py:214 (update → get) и :276 (list_recent → get)
были классифицированы как USER_DATA в W3.1 — нет tenant filter
на Redis lookup. Per ADR-0345 Option A требуется tenant predicate.

Этот тест ДОКУМЕНТИРУЕТ gap (debt) — не fix.
Negative test FAILING = current code lacks tenant isolation (real P0).
Per v6 §3: «расхождение runtime != architecture фиксируй как debt,
а не «исправляй» молча».
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeRedis:
    """In-memory fake Redis with cache_get/cache_set/cache_delete + execute pipeline API."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def cache_get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def cache_set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        self.store[key] = value

    async def cache_delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def execute(self, store_name: str, op: Any) -> Any:
        """Mimic redis.execute("cache", lambda conn: pipeline_op).

        Calls op(self) — op is callable that takes a FakeConn-like object.
        """
        conn = _FakeConn(self.store)
        return await op(conn)


class _FakeConn:
    """Fake Redis connection with pipeline support."""

    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self._pipeline: list[tuple[str, tuple]] = []

    def pipeline(self, transaction: bool = True) -> "_FakePipeline":
        self._pipeline = []
        return _FakePipeline(self._store)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        return 1

    async def zrevrange(self, key: str, start: int, end: int) -> list[bytes]:
        return []


class _FakePipeline:
    """Fake Redis pipeline: collect ops, execute on .execute()."""

    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self._ops: list[tuple[str, tuple]] = []

    def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self._ops.append(("set", (key, value, ex)))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._ops.append(("zadd", (key, mapping)))

    def zremrangebyrank(self, key: str, start: int, end: int) -> None:
        self._ops.append(("zremrangebyrank", (key, start, end)))

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, args in self._ops:
            if op == "set":
                key, value, ex = args
                self._store[key] = value
                results.append(True)
        return results


@pytest.fixture()
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture()
def store(fake_redis, monkeypatch):
    """RedisIngestStateStore с fake redis подменой."""
    from src.backend.services.ai import rag_ingest_store

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", lambda: fake_redis
    )
    yield rag_ingest_store.RedisIngestStateStore()
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_get_returns_none_for_unrelated_task(store, fake_redis):
    """Sanity: get(unknown_id) returns None.

    Baseline — корректное поведение для несуществующего task.
    """
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_does_not_filter_by_tenant(store, fake_redis):
    """Per W3.1 classification: RedisIngestStateStore.get НЕ фильтрует по tenant.

    Этот тест документирует существующее поведение: tenant A создаёт
    task → tenant B читает task → возвращается payload (НЕ tenant-scoped).

    Per v6 W3.2: SHOULD return None (tenant filter). Current behavior: returns.
    Negative test FAILS until tenant-isolation fix.
    """
    payload = {
        "tenant_id": "tenant_A",
        "url": "https://example.com/doc.pdf",
        "status": "pending",
    }

    # Tenant A creates task.
    await store.create(task_id="task-abc-123", payload=payload)

    # Simulate tenant B caller attempting to read tenant A's task.
    # Per v6 W3.2: SHOULD return None (tenant filter).
    # Current behavior (BUG): returns tenant A's payload.
    result = await store.get("task-abc-123")

    assert result is None, (
        f"TENANT_ISOLATION_DEBT: RedisIngestStateStore.get(task_id) returned "
        f"task from tenant A without tenant filter. task_id=task-abc-123, "
        f"result={result}. Per v6 §10 W3 + ADR-0345 Option A: должен быть "
        f"tenant predicate filter. See docs/roadmap/W3_UNKNOWN_OWNERSHIP_"
        f"CLASSIFICATION_2026-09-24.md раздел 2.1."
    )
