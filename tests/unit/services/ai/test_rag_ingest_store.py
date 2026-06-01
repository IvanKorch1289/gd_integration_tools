"""Тесты IngestStateStore (Wave D.2)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.services.ai.rag_ingest_store import (
    InMemoryIngestStateStore,
    RedisIngestStateStore,
    build_ingest_state_store,
)


@pytest.mark.asyncio
async def test_inmemory_create_update_get_roundtrip() -> None:
    store = InMemoryIngestStateStore()
    await store.create("t1", {"task_id": "t1", "status": "running", "processed": 0})
    snap = await store.get("t1")
    assert snap is not None and snap["status"] == "running"

    await store.update("t1", status="completed", processed=5)
    snap2 = await store.get("t1")
    assert snap2["status"] == "completed" and snap2["processed"] == 5


@pytest.mark.asyncio
async def test_inmemory_list_recent_returns_newest_first() -> None:
    store = InMemoryIngestStateStore()
    await store.create("a", {"task_id": "a"})
    await store.create("b", {"task_id": "b"})
    await store.create("c", {"task_id": "c"})
    items = await store.list_recent(limit=2)
    assert [it["task_id"] for it in items] == ["c", "b"]


@pytest.mark.asyncio
async def test_inmemory_get_missing_returns_none() -> None:
    store = InMemoryIngestStateStore()
    assert await store.get("none") is None


@pytest.mark.asyncio
async def test_build_factory_memory_default() -> None:
    store = build_ingest_state_store(None)
    assert isinstance(store, InMemoryIngestStateStore)


@pytest.mark.asyncio
async def test_build_factory_redis_kind() -> None:
    store = build_ingest_state_store("redis")
    assert isinstance(store, RedisIngestStateStore)


@pytest.mark.asyncio
async def test_redis_store_create_uses_pipeline() -> None:
    """Минимальная проверка: create вызывает execute('cache', op) на pipeline."""

    class _FakePipe:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def set(self, key: Any, value: Any, ex: int) -> None:
            self.calls.append(("set", key))

        def zadd(self, key: str, mapping: dict) -> None:
            self.calls.append(("zadd", mapping))

        def zremrangebyrank(self, key: str, a: int, b: int) -> None:
            self.calls.append(("zrem", (a, b)))

        async def execute(self) -> None:
            self.calls.append(("execute", None))

    class _FakeConn:
        def __init__(self) -> None:
            self.pipe = _FakePipe()

        def pipeline(self, transaction: bool = False) -> _FakePipe:
            return self.pipe

    class _FakeClient:
        def __init__(self) -> None:
            self.conn = _FakeConn()

        async def execute(self, kind: str, op: Any) -> Any:
            return await op(self.conn)

    client = _FakeClient()
    store = RedisIngestStateStore(redis_client=client, ttl_seconds=10)
    await store.create("t1", {"status": "running"})
    methods = {c[0] for c in client.conn.pipe.calls}
    assert {"set", "zadd", "execute"} <= methods
