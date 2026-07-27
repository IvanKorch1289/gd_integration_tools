"""ClickHouse admin client singleton (S176 fix).

Закрывает anti-pattern из Infrastructure audit: admin endpoints
``admin_workflow_audit.py`` и ``admin_workflow_cost.py`` создавали
новый ``clickhouse_connect.get_async_client()`` на каждый вызов.

S176 fix: singleton через :func:`app_state_singleton` decorator — переиспользует
HTTPX connection pool между requests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from src.backend.core.logging import get_logger

__all__ = ("AdminClickHouseClient", "get_admin_clickhouse_client")

_logger = get_logger(__name__)


class AdminClickHouseClient(Protocol):
    """Typed subset of clickhouse-connect's dynamic async client."""

    def query(self, *args: Any, **kwargs: Any) -> Awaitable[Any]: ...


_admin_client: AdminClickHouseClient | None = None


async def get_admin_clickhouse_client() -> AdminClickHouseClient | None:
    """Return one process-wide async ClickHouse client.

    ``clickhouse_connect`` has no stable exported client type, therefore the
    runtime object is narrowed to the query-only protocol used by admin pages.
    """
    global _admin_client
    if _admin_client is not None:
        return _admin_client

    try:
        from clickhouse_connect import get_async_client

        from src.backend.core.config import settings

        host = (
            getattr(settings.clickhouse, "host", "localhost")
            if hasattr(settings, "clickhouse")
            else "localhost"
        )
        port = (
            getattr(settings.clickhouse, "port", 8123)
            if hasattr(settings, "clickhouse")
            else 8123
        )
        database = (
            getattr(settings.clickhouse, "database", "default")
            if hasattr(settings, "clickhouse")
            else "default"
        )
        factory = cast(Callable[..., Awaitable[Any]], get_async_client)
        _admin_client = cast(
            AdminClickHouseClient,
            await factory(host=host, port=port, database=database),
        )
        return _admin_client
    except Exception as exc:
        _logger.warning("ClickHouse admin client unavailable: %s", exc)
        return None
