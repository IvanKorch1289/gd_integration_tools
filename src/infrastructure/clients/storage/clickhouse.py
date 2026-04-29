"""Async ClickHouse client — batch insert, query, aggregations."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("ClickHouseClient", "get_clickhouse_client")

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """Асинхронный клиент ClickHouse через HTTP-интерфейс.

    Использует httpx для HTTP-запросов к ClickHouse HTTP API,
    что позволяет работать без нативного драйвера.
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
        self._client: Any = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._host}:{self._http_port}"

    async def connect(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=self._connect_timeout,
                read=self._send_receive_timeout,
                write=self._send_receive_timeout,
                pool=self._connect_timeout,
            ),
            auth=(self._user, self._password) if self._password else None,
        )
        logger.info("ClickHouse client connected to %s", self.base_url)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("ClickHouse client disconnected")

    async def _ensure_client(self) -> Any:
        if self._client is None:
            await self.connect()
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
        """Batch INSERT — разбивает на chunk-и по max_batch_size."""
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
    from src.core.config.clickhouse import clickhouse_settings

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
    )


from src.core.di import app_state_singleton


@app_state_singleton("clickhouse_client", _create_clickhouse_client)
def get_clickhouse_client() -> ClickHouseClient:
    """Возвращает ClickHouseClient из app.state или lazy-init fallback."""
