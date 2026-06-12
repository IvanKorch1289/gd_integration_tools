"""W23 — Единый dedup-helper для Source-инстансов.

``DedupeStore`` Protocol хранит ``event_id`` с TTL: первое появление —
``False`` (= не дубль, продолжаем обработку), повторное — ``True``.

Реализации:

* :class:`MemoryDedupeStore` — на ``cachetools.TTLCache`` (dev_light/тесты).
* :class:`RedisDedupeStore` — на ``redis.set(NX)`` + ``EX`` (prod).

Не хранит payload — только сам ``event_id`` как ключ. Префикс
``namespace`` отделяет разные источники друг от друга.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from cachetools import TTLCache

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("DedupeStore", "MemoryDedupeStore", "RedisDedupeStore")

logger = get_logger("services.sources.idempotency")


@runtime_checkable
class DedupeStore(Protocol):
    """Контракт хранилища дедупликации событий по ``event_id``."""

    async def is_duplicate(self, namespace: str, event_id: str) -> bool:
        """Проверить и атомарно зарегистрировать ``event_id``.

        Args:
            namespace: Префикс (``source_id`` / ``kind``).
            event_id: Уникальный id события из :class:`SourceEvent`.

        Returns:
            ``True`` если событие уже видели (дубль), иначе ``False``.
        """
        ...


class MemoryDedupeStore:
    """In-process dedup на ``cachetools.TTLCache``.

    Используется в dev_light/unit-тестах. ``maxsize`` ограничивает RAM,
    ``ttl_seconds`` — время удержания записи.
    """

    def __init__(
        self, *, maxsize: int = 100_000, ttl_seconds: float = 86_400.0
    ) -> None:
        self._cache: TTLCache[str, bool] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = asyncio.Lock()

    async def is_duplicate(self, namespace: str, event_id: str) -> bool:
        key = f"{namespace}:{event_id}"
        async with self._lock:
            if key in self._cache:
                return True
            self._cache[key] = True
            return False


class RedisDedupeStore:
    """Dedup поверх Redis ``SET NX EX`` (атомарная регистрация first-write).

    Не блокирует event loop: использует ``redis.asyncio``.

    **Failure mode** (S71 W3, TD-S64-W4 closure):

    * ``fail_closed=False`` (default, legacy): ошибки Redis деградируются
      в ``False`` (best-effort, лучше пропустить дубль, чем уронить
      hot-path). Подходит для dev_light / observability-grade профилей.
    * ``fail_closed=True`` (prod-рекомендация): ошибки Redis → ``raise``,
      гарантирует strong-consistency семантику. В multi-instance setup
      дубли событий при flapping Redis недопустимы для финансовых /
      regulatory workloads.

    Default оставлен ``False`` для backward-compat (S71 W3 не breaking
    change). Prod-профили должны переопределять явно.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = 86_400,
        key_prefix: str = "dedup:",
        fail_closed: bool = False,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = key_prefix
        self._fail_closed = fail_closed

    async def is_duplicate(self, namespace: str, event_id: str) -> bool:
        key = f"{self._prefix}{namespace}:{event_id}"
        try:
            stored = await self._redis.set(key, b"1", nx=True, ex=self._ttl)
        except Exception as exc:
            if self._fail_closed:
                logger.error(
                    "RedisDedupeStore failed in fail-closed mode (re-raising): %s",
                    exc,
                )
                raise
            logger.warning("RedisDedupeStore failed (degrade to non-dup): %s", exc)
            return False
        # ``set NX`` returns True если ключа не было (первая запись)
        # либо None если ключ уже есть.
        return stored is None
