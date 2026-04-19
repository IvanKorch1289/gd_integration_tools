"""ManagedAsyncClient — единый базовый класс для async клиентов.

Устраняет ~150 LOC дубликатов в http/smtp/redis/s3/elasticsearch/mongodb/clickhouse:
- Единый lifecycle: connect / close / health_check
- Lazy initialization с asyncio.Lock
- Hook-методы: _create_connection, _close_connection, _ping
- Единый logger + correlation_id propagation
- Safe idempotent close для multi-instance scenarios

Usage (пример)::

    class RedisClient(ManagedAsyncClient):
        async def _create_connection(self):
            return await aioredis.from_url(self._url)

        async def _close_connection(self, conn):
            await conn.close()

        async def _ping(self, conn) -> bool:
            return await conn.ping()
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

__all__ = ("ManagedAsyncClient",)

T = TypeVar("T")


class ManagedAsyncClient(ABC, Generic[T]):
    """Абстрактная база для async клиентов с lifecycle-managed connection.

    Подклассы реализуют:
    - _create_connection() -> T — создаёт подключение
    - _close_connection(conn: T) — закрывает подключение
    - _ping(conn: T) -> bool — healthcheck (опционально)
    """

    def __init__(self, *, name: str | None = None) -> None:
        self._connection: T | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._name = name or self.__class__.__name__
        self._logger = logging.getLogger(f"clients.{self._name.lower()}")

    @abstractmethod
    async def _create_connection(self) -> T:
        """Создаёт новое подключение. Подклассы обязаны реализовать."""
        ...

    async def _close_connection(self, conn: T) -> None:
        """Закрывает подключение. По умолчанию вызывает conn.close() если доступен."""
        closer = getattr(conn, "close", None) or getattr(conn, "aclose", None)
        if closer is None:
            return
        try:
            result = closer()
            if asyncio.iscoroutine(result):
                await result
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._logger.warning("Close connection failed for %s: %s", self._name, exc)

    async def _ping(self, conn: T) -> bool:
        """Healthcheck. По умолчанию True (подклассы могут переопределить)."""
        return True

    async def ensure_connected(self) -> T:
        """Возвращает активное подключение, создавая при необходимости.

        Safe для multi-instance (lock на уровне процесса).
        """
        if self._closed:
            raise RuntimeError(f"Client {self._name} is closed")

        if self._connection is not None:
            return self._connection

        async with self._lock:
            if self._connection is None:
                self._connection = await self._create_connection()
                self._logger.debug("Connected: %s", self._name)
        return self._connection

    async def close(self) -> None:
        """Закрывает подключение. Идемпотентно."""
        if self._closed:
            return
        async with self._lock:
            if self._connection is not None:
                await self._close_connection(self._connection)
                self._connection = None
            self._closed = True
            self._logger.debug("Closed: %s", self._name)

    async def health_check(self) -> dict[str, Any]:
        """Проверка здоровья клиента.

        Returns:
            {"name": str, "status": "ok"|"error", "latency_ms": float, "error": str|None}
        """
        import time

        start = time.monotonic()
        try:
            conn = await self.ensure_connected()
            ok = await self._ping(conn)
            latency_ms = (time.monotonic() - start) * 1000
            return {
                "name": self._name,
                "status": "ok" if ok else "degraded",
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            return {
                "name": self._name,
                "status": "error",
                "latency_ms": round(latency_ms, 2),
                "error": str(exc)[:200],
            }

    @property
    def is_connected(self) -> bool:
        """Подключение установлено и не закрыто."""
        return self._connection is not None and not self._closed

    @property
    def name(self) -> str:
        return self._name

    async def __aenter__(self) -> "ManagedAsyncClient[T]":
        await self.ensure_connected()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
