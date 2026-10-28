"""ClickHouse admin client singleton (S176 fix).

Закрывает anti-pattern из Infrastructure audit: admin endpoints
``admin_workflow_audit.py`` и ``admin_workflow_cost.py`` создавали
новый ``clickhouse_connect.get_async_client()`` на каждый вызов.

S176 fix: singleton через :func:`app_state_singleton` decorator — переиспользует
HTTPX connection pool между requests.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol, cast

from src.backend.core.logging import get_logger

__all__ = ("AdminClickHouseClient", "get_admin_clickhouse_client")

_logger = get_logger(__name__)


class AdminClickHouseClient(Protocol):
    """Typed subset of clickhouse-connect's dynamic async client."""

    def query(self, *args: Any, **kwargs: Any) -> Awaitable[Any]:
        """Метод query (см. signature)."""
        ...


_admin_client: AdminClickHouseClient | None = None


async def get_admin_clickhouse_client() -> AdminClickHouseClient | None:
    """Return one process-wide async ClickHouse client.

    ``clickhouse_connect`` has no stable exported client type, therefore the
    runtime object is narrowed to the query-only protocol used by admin pages.

    Admin pages are a read-only UI path: if the optional
    ``clickhouse_connect`` driver is missing (Wave 13 Q8 — the package is not
    declared in the manifest yet) or ClickHouse is down, the helper degrades
    to ``None`` with a warning instead of failing the request.
    """
    global _admin_client
    if _admin_client is not None:
        return _admin_client

    try:
        from src.backend.infrastructure.clients.storage.clickhouse_driver import (
            create_clickhouse_async_client,
        )

        client = await create_clickhouse_async_client(required=False)
        if client is None:
            return None
        _admin_client = cast(AdminClickHouseClient, client)
        return _admin_client
    except Exception as exc:
        _logger.warning("ClickHouse admin client unavailable: %s", exc)
        return None
