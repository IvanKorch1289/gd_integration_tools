"""AnalyticsService — аналитика через ClickHouse."""

from __future__ import annotations

from typing import Any

from src.core.di.providers import get_clickhouse_client_provider
from src.core.interfaces.integrations import ClickHouseClientProtocol

__all__ = ("AnalyticsService", "get_analytics_service")


class AnalyticsService:
    """Сервис аналитики — batch insert, query, aggregations через ClickHouse."""

    def __init__(self, client: ClickHouseClientProtocol) -> None:
        self._client = client

    async def insert_event(self, table: str, event: dict[str, Any]) -> int:
        """Вставляет одно аналитическое событие."""
        return await self._client.insert(table, [event])

    async def insert_batch(self, table: str, events: list[dict[str, Any]]) -> int:
        """Batch insert аналитических событий."""
        return await self._client.insert(table, events)

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Произвольный SELECT-запрос."""
        return await self._client.query(sql, params)

    async def count(self, table: str, where: str | None = None) -> int:
        """COUNT(*) с опциональным WHERE."""
        result = await self._client.aggregate(table, "count", "*", where=where)
        if result:
            return int(result[0].get("value", 0))
        return 0

    async def aggregate(
        self,
        table: str,
        agg_func: str,
        column: str,
        group_by: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """Агрегация: count, sum, avg, min, max."""
        return await self._client.aggregate(
            table, agg_func, column, group_by=group_by, where=where
        )

    async def health(self) -> bool:
        """Проверка доступности ClickHouse."""
        return await self._client.ping()


_analytics_service_instance: AnalyticsService | None = None


def get_analytics_service() -> AnalyticsService:
    global _analytics_service_instance
    if _analytics_service_instance is None:
        _analytics_service_instance = AnalyticsService(
            client=get_clickhouse_client_provider()
        )
    return _analytics_service_instance
