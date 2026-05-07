"""Async ClickHouse client — batch insert, query, aggregations.

Wave Sprint 0 (V16, ClickHouse pool hotfix):

* Один singleton ``ClickHouseClient`` на процесс через ``app_state_singleton``.
* Persistent HTTP connection pool на базе ``httpx.AsyncClient`` +
  ``httpx.Limits(max_connections, max_keepalive_connections, keepalive_expiry)``.
* TTL клиента (``recycle_seconds``): по истечении ttl соединения пересоздаются,
  что эквивалентно ``pool_recycle`` в SQLAlchemy и предотвращает «зависшие»
  TCP-сессии после долгого idle.
* Опциональный ``pool_pre_ping`` (HTTP ``/ping``) перед использованием
  клиента после простоя — аналог ``pool_pre_ping`` SQLAlchemy.
* НЕ создаём ``httpx.AsyncClient()`` per-request — все запросы идут через
  один shared client из пула.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.backend.core.di import app_state_singleton

__all__ = ("ClickHouseClient", "get_clickhouse_client")

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """Асинхронный singleton-клиент ClickHouse через HTTP-интерфейс.

    Использует ``httpx.AsyncClient`` с persistent connection pool. Один
    инстанс переиспользуется на всём процессе (см. :func:`get_clickhouse_client`
    и DI ``app.state.clickhouse_client``).

    Pool-параметры берутся из :class:`ClickHouseSettings` и пробрасываются
    в ``httpx.Limits`` + ``httpx.Timeout``.
    """

    def __init__(
        self,
        host: str = "localhost",
        http_port: int = 8123,
        database: str = "default",
        user: str = "default",
        password: str = "",
        secure: bool = False,
        connect_timeout: int = 10,
        send_receive_timeout: int = 300,
        max_batch_size: int = 10000,
        pool_size: int = 20,
        pool_overflow: int = 10,
        keepalive_expiry: float = 30.0,
        recycle_seconds: int = 3600,
        pool_pre_ping: bool = True,
        max_connections: int = 100,
    ) -> None:
        self._host = host
        self._http_port = http_port
        self._database = database
        self._user = user
        self._password = password
        self._secure = secure
        self._connect_timeout = connect_timeout
        self._send_receive_timeout = send_receive_timeout
        self._max_batch_size = max_batch_size

        # ── pool params ──
        self._pool_size = pool_size
        self._pool_overflow = pool_overflow
        self._keepalive_expiry = keepalive_expiry
        self._recycle_seconds = recycle_seconds
        self._pool_pre_ping = pool_pre_ping
        self._max_connections = max_connections

        self._client: Any = None
        self._client_created_at: float = 0.0
        self._last_used_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Базовый URL ClickHouse HTTP-интерфейса."""
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._host}:{self._http_port}"

    def _build_client(self) -> Any:
        """Создаёт новый ``httpx.AsyncClient`` с pool-настройками."""
        import httpx

        # max_keepalive_connections не должно превышать max_connections (httpx требование).
        keepalive = min(self._pool_size + self._pool_overflow, self._max_connections)
        limits = httpx.Limits(
            max_connections=self._max_connections,
            max_keepalive_connections=keepalive,
            keepalive_expiry=self._keepalive_expiry,
        )
        timeout = httpx.Timeout(
            connect=float(self._connect_timeout),
            read=float(self._send_receive_timeout),
            write=float(self._send_receive_timeout),
            pool=float(self._connect_timeout),
        )
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=limits,
            auth=(self._user, self._password) if self._password else None,
        )

    async def connect(self) -> None:
        """Инициализирует HTTP-клиент с persistent pool (если ещё не создан)."""
        async with self._lock:
            if self._client is None:
                self._client = self._build_client()
                self._client_created_at = time.monotonic()
                self._last_used_at = self._client_created_at
                logger.info(
                    "ClickHouse client connected to %s "
                    "(pool_size=%d, overflow=%d, max=%d, keepalive=%.1fs, ttl=%ds)",
                    self.base_url,
                    self._pool_size,
                    self._pool_overflow,
                    self._max_connections,
                    self._keepalive_expiry,
                    self._recycle_seconds,
                )

    async def close(self) -> None:
        """Закрывает HTTP-клиент и освобождает все TCP-соединения пула."""
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
                logger.info("ClickHouse client disconnected")

    async def _ensure_client(self) -> Any:
        """Гарантирует наличие живого клиента: lazy-init + recycle + pre-ping."""
        # Recycle: пересоздаём клиента по истечении TTL.
        if self._client is not None and self._recycle_seconds > 0:
            age = time.monotonic() - self._client_created_at
            if age >= self._recycle_seconds:
                logger.debug(
                    "Recycling ClickHouse client (age=%.1fs >= ttl=%ds)",
                    age,
                    self._recycle_seconds,
                )
                await self.close()

        if self._client is None:
            await self.connect()

        # Pre-ping после простоя — defensive health-check.
        if (
            self._pool_pre_ping
            and self._last_used_at > 0
            and (time.monotonic() - self._last_used_at) > self._keepalive_expiry
        ):
            try:
                response = await self._client.get("/ping")
                if response.status_code != 200:
                    raise RuntimeError(f"ping returned {response.status_code}")
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
                logger.warning(
                    "ClickHouse pre-ping failed (%s) — recreating pool",
                    exc,
                )
                await self.close()
                await self.connect()

        self._last_used_at = time.monotonic()
        return self._client

    async def execute(self, query: str, params: dict[str, Any] | None = None) -> str:
        """Выполняет произвольный SQL-запрос."""
        client = await self._ensure_client()
        request_params = {"database": self._database, "query": query}
        if params:
            request_params.update(params)
        response = await client.get("/", params=request_params)
        response.raise_for_status()
        return response.text

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECT запрос, возвращает список словарей."""
        import json

        full_query = f"{sql} FORMAT JSONEachRow"
        raw = await self.execute(full_query, params)
        if not raw.strip():
            return []
        return [json.loads(line) for line in raw.strip().split("\n") if line.strip()]

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Batch INSERT — разбивает на chunk-и по ``max_batch_size``."""
        import json

        if not rows:
            return 0

        client = await self._ensure_client()
        total = 0

        for i in range(0, len(rows), self._max_batch_size):
            chunk = rows[i : i + self._max_batch_size]
            data = "\n".join(json.dumps(row, default=str) for row in chunk)
            response = await client.post(
                "/",
                params={
                    "database": self._database,
                    "query": f"INSERT INTO {table} FORMAT JSONEachRow",
                },
                content=data.encode(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            total += len(chunk)

        logger.info("Inserted %d rows into %s", total, table)
        return total

    async def aggregate(
        self,
        table: str,
        agg_func: str,
        column: str,
        group_by: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """Агрегация — count, sum, avg, min, max."""
        parts = [f"SELECT {agg_func}({column}) as value"]
        if group_by:
            parts[0] = f"SELECT {group_by}, {agg_func}({column}) as value"
        parts.append(f"FROM {table}")
        if where:
            parts.append(f"WHERE {where}")
        if group_by:
            parts.append(f"GROUP BY {group_by}")
        return await self.query(" ".join(parts))

    async def create_table(self, ddl: str) -> None:
        """Создаёт таблицу по DDL."""
        await self.execute(ddl)
        logger.info("Table created via DDL")

    async def ping(self) -> bool:
        """Проверка доступности ClickHouse."""
        try:
            client = await self._ensure_client()
            response = await client.get("/ping")
            return response.status_code == 200
        except (ConnectionError, TimeoutError, OSError):
            return False


def _create_clickhouse_client() -> ClickHouseClient:
    """Lazy-фабрика singleton-клиента из ``ClickHouseSettings``."""
    from src.backend.core.config.clickhouse import clickhouse_settings

    return ClickHouseClient(
        host=clickhouse_settings.host,
        http_port=clickhouse_settings.http_port,
        database=clickhouse_settings.database,
        user=clickhouse_settings.user,
        password=clickhouse_settings.password,
        secure=clickhouse_settings.secure,
        connect_timeout=clickhouse_settings.connect_timeout,
        send_receive_timeout=clickhouse_settings.send_receive_timeout,
        max_batch_size=clickhouse_settings.max_batch_size,
        pool_size=clickhouse_settings.pool_size,
        pool_overflow=clickhouse_settings.pool_overflow,
        keepalive_expiry=clickhouse_settings.keepalive_expiry,
        recycle_seconds=clickhouse_settings.recycle_seconds,
        pool_pre_ping=clickhouse_settings.pool_pre_ping,
        max_connections=clickhouse_settings.max_connections,
    )


@app_state_singleton("clickhouse_client", _create_clickhouse_client)
def get_clickhouse_client() -> ClickHouseClient:
    """Возвращает singleton ``ClickHouseClient`` из ``app.state`` (или lazy-init).

    Декоратор :func:`app_state_singleton` подменяет тело функции — оно
    оставлено пустым специально (никогда не вызывается).
    """
