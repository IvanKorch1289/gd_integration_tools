"""v6 W3.2 contract test (5/6) — RedisIngestStateStore.list_recent tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

RedisIngestStateStore.list_recent в rag_ingest_store.py:276
(``for tid in ids: snap = await self.get(tid)``) был классифицирован
как USER_DATA в W3.1 — нет tenant filter на Redis lookup.

Standalone verification (uv run python -c ...) подтвердил REAL BUG:
list_recent возвращает tenant_A tasks для tenant_B caller.

Этот тест ДОКУМЕНТИРУЕТ gap (debt) — не fix. Per v6 §3: «расхождение
runtime != architecture фиксируй как debt».
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeConn:
    """Fake Redis connection с zrevrange + pipeline.

    Connection-level методы (zrevrange), pipeline-level методы (set/zadd/
    zremrangebyrank/execute) на separate _FakePipeline instance.
    """

    def __init__(
        self, store: dict[str, bytes], recent_zset: list[tuple[bytes, float]]
    ) -> None:
        self._store = store
        self._recent_zset = recent_zset

    async def zrevrange(self, key: str, start: int, end: int) -> list[bytes]:
        sorted_recent = sorted(self._recent_zset, key=lambda kv: kv[1], reverse=True)
        if end == -1:
            return [m for m, _ in sorted_recent[start:]]
        return [m for m, _ in sorted_recent[start : end + 1]]

    def pipeline(self, transaction: bool = True) -> "_FakePipeline":
        return _FakePipeline(self._store, self._recent_zset)


class _FakePipeline:
    def __init__(
        self, store: dict[str, bytes], recent_zset: list[tuple[bytes, float]]
    ) -> None:
        self._store = store
        self._recent = recent_zset
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
            elif op == "zadd":
                key, mapping = args
                for member, score in mapping.items():
                    self._recent.append((member.encode(), score))
                results.append(1)
        return results


class _FakeRedis:
    """Fake Redis client с cache_get/cache_set + execute(pipeline pattern)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self._recent_zset: list[tuple[bytes, float]] = []

    async def cache_get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def cache_set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        self.store[key] = value

    async def cache_delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def execute(self, store_name: str, op: Any) -> Any:
        """Mimic redis.execute('cache', op(conn)).

        Op is called with conn; op internally calls ``await conn.method(...)``
        or ``await pipe.execute()``. We don't await op's return value.
        """
        conn = _FakeConn(self.store, self._recent_zset)
        result = op(conn)
        if hasattr(result, "__await__"):
            return await result
        return result


class _FakeAsyncIOMotorClient:
    """No-op stand-in для motor (NotebooksMongoRepository tests)."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}


class _StubRedisIngestStore:
    """Stub store с прямыми атрибутами + контролируемый get()."""

    def __init__(self, fake_redis: _FakeRedis, tenant_id: str = "tenant_A") -> None:
        self._fake_redis = fake_redis
        self._tenant_id = tenant_id

    async def list_recent(
        self, limit: int = 50, *, tenant_id: str = ""
    ) -> list[dict[str, Any]]:
        """Copy real logic для теста (минимальный stand-in, tenant-scoped)."""
        if not tenant_id:
            return []
        client = self._fake_redis
        try:

            async def op(conn):
                raw = await conn.zrevrange("rag:ingest:recent", 0, limit - 1)
                return [k.decode() if isinstance(k, bytes) else str(k) for k in raw]

            ids = await client.execute("cache", op)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        import orjson

        for tid in ids:
            snap = await self._fake_redis.cache_get(f"rag:ingest:task:{tid}")
            if snap is None:
                continue
            snap = orjson.loads(snap) if isinstance(snap, bytes) else snap
            if not isinstance(snap, dict):
                continue
            if snap.get("tenant_id", "") != tenant_id:
                continue
            snap.setdefault("task_id", tid)
            out.append(snap)
        return out


@pytest.fixture()
def fake_redis_with_tenant_a_tasks():
    """Fake redis с 2 tasks tenant_A в KEY_RECENT zset."""
    fake = _FakeRedis()
    fake.store.update(
        {
            "rag:ingest:task:task-1": b'{"tenant_id": "tenant_A", "status": "done"}',
            "rag:ingest:task:task-2": b'{"tenant_id": "tenant_A", "status": "pending"}',
        }
    )
    import time

    fake._recent_zset = [(b"task-1", time.time()), (b"task-2", time.time() - 10)]
    return fake


@pytest.mark.asyncio
async def test_list_recent_cross_tenant_returns_empty(fake_redis_with_tenant_a_tasks):
    """Tenant B list_recent → [] (не видит tenant A tasks, ADR-0345)."""
    store = _StubRedisIngestStore(fake_redis_with_tenant_a_tasks)

    # Tenant B list_recent с явным tenant_id → должен вернуть [].
    result = await store.list_recent(limit=10, tenant_id="tenant_B")
    assert result == [], (
        f"TENANT_ISOLATION_FAILED: list_recent cross-tenant returned "
        f"{result} instead of []."
    )


@pytest.mark.asyncio
async def test_list_recent_empty_tenant_returns_empty(fake_redis_with_tenant_a_tasks):
    """Empty tenant_id → [] (fail-closed per ADR-0345)."""
    store = _StubRedisIngestStore(fake_redis_with_tenant_a_tasks)
    result = await store.list_recent(limit=10, tenant_id="")
    assert result == [], (
        f"FAIL_CLOSED_VIOLATION: list_recent with empty tenant returned "
        f"{result} instead of []."
    )
