"""Состояние RAG ingest-задач: in-memory и Redis-backed реализации (D.2).

Wave D.2 / Track D AI: persistent task-store для долгоживущих ingest'ов.
Старый ``RagIngestService._tasks`` (dict) теряет прогресс при рестарте;
``RedisIngestStateStore`` использует Redis HASH с TTL для durability.

API сознательно узкий — Protocol ``IngestStateStore``:

* ``create(task_id, payload)`` — первичная запись задачи;
* ``update(task_id, **fields)`` — патч полей (status / processed / errors / ...);
* ``get(task_id)`` — снимок состояния либо ``None``;
* ``list_recent(limit)`` — последние N задач.

Backward-compat: ``InMemoryIngestStateStore`` остаётся default-фабрикой —
зависимости от Redis нет.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

import orjson

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = (
    "InMemoryIngestStateStore",
    "IngestStateStore",
    "RedisIngestStateStore",
    "build_ingest_state_store",
)


@runtime_checkable
class IngestStateStore(Protocol):
    """Async-протокол хранилища состояний ingest-задач."""

    async def create(self, task_id: str, payload: dict[str, Any]) -> None: ...

    async def update(self, task_id: str, **fields: Any) -> None: ...

    async def get(self, task_id: str) -> dict[str, Any] | None: ...

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]: ...


class InMemoryIngestStateStore:
    """In-process реализация (Sprint <D.2 baseline). Без durability."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()

    async def create(self, task_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._tasks[task_id] = dict(payload)
            self._order.append(task_id)

    async def update(self, task_id: str, **fields: Any) -> None:
        async with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return
            entry.update(fields)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        entry = self._tasks.get(task_id)
        return dict(entry) if entry is not None else None

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        recent_ids = list(reversed(self._order))[: max(int(limit), 0)]
        return [dict(self._tasks[tid]) for tid in recent_ids if tid in self._tasks]


class RedisIngestStateStore:
    """Redis-backed store. HASH per task + sorted set ``recent`` для list_recent.

    Ключи:
        rag:ingest:task:<task_id> — HASH, поле ``json`` хранит сериализованный snapshot.
        rag:ingest:recent — ZSET, score = ts.

    TTL по умолчанию — 24 часа.
    """

    KEY_TASK = "rag:ingest:task:{task_id}"
    KEY_RECENT = "rag:ingest:recent"

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        ttl_seconds: int = 86_400,
        recent_max: int = 200,
    ) -> None:
        self._client = redis_client
        self._ttl = int(ttl_seconds)
        self._recent_max = int(recent_max)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from src.backend.core.storage.redis import get_redis_client

        self._client = get_redis_client()
        return self._client

    def _task_key(self, task_id: str) -> str:
        return self.KEY_TASK.format(task_id=task_id)

    async def create(self, task_id: str, payload: dict[str, Any]) -> None:
        client = self._ensure_client()
        raw = orjson.dumps(payload)
        key = self._task_key(task_id)
        try:

            async def op(conn: Any) -> None:
                pipe = conn.pipeline(transaction=False)
                pipe.set(key, raw, ex=self._ttl)
                pipe.zadd(self.KEY_RECENT, {task_id: float(_now_score())})
                pipe.zremrangebyrank(self.KEY_RECENT, 0, -(self._recent_max + 1))
                await pipe.execute()

            await client.execute("cache", op)
        except Exception as exc:
            logger.debug("RedisIngestStateStore.create failed: %s", exc)

    async def update(self, task_id: str, **fields: Any) -> None:
        snapshot = await self.get(task_id)
        if snapshot is None:
            snapshot = dict(fields)
        else:
            snapshot.update(fields)
        client = self._ensure_client()
        try:
            await client.cache_set(
                self._task_key(task_id), orjson.dumps(snapshot), self._ttl
            )
        except Exception as exc:
            logger.debug("RedisIngestStateStore.update failed: %s", exc)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        client = self._ensure_client()
        try:
            raw = await client.cache_get(self._task_key(task_id))
        except Exception as exc:
            logger.debug("RedisIngestStateStore.get failed: %s", exc)
            return None
        if not raw:
            return None
        try:
            data = orjson.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("RedisIngestStateStore decode failed: %s", exc)
            return None

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        client = self._ensure_client()
        limit = max(int(limit), 0)
        try:

            async def op(conn: Any) -> list[str]:
                raw = await conn.zrevrange(self.KEY_RECENT, 0, limit - 1)
                return [k.decode() if isinstance(k, bytes) else str(k) for k in raw]

            ids: list[str] = await client.execute("cache", op)
        except Exception as exc:
            logger.debug("RedisIngestStateStore.list_recent failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for tid in ids:
            snap = await self.get(tid)
            if snap is not None:
                snap.setdefault("task_id", tid)
                out.append(snap)
        return out


def _now_score() -> float:
    """Текущая метка времени в секундах (для ZSET score)."""
    import time

    return time.time()


def build_ingest_state_store(backend: str | None = None) -> IngestStateStore:
    """Фабрика по ``rag_ingest_settings.state_backend`` (memory/redis)."""
    name = (backend or "memory").strip().lower()
    if name == "redis":
        return RedisIngestStateStore()
    return InMemoryIngestStateStore()
