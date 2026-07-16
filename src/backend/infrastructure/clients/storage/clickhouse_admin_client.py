"""ClickHouse admin client singleton (S176 fix).

Закрывает anti-pattern из Infrastructure audit: admin endpoints
``admin_workflow_audit.py`` и ``admin_workflow_cost.py`` создавали
новый ``clickhouse_connect.get_async_client()`` на каждый вызов.

S176 fix: singleton через :func:`app_state_singleton` decorator — переиспользует
HTTPX connection pool между requests.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.logging import get_logger

__all__ = ("get_admin_clickhouse_client",)

_logger = get_logger(__name__)


@app_state_singleton
async def get_admin_clickhouse_client() -> Any:
    """Singleton factory для ClickHouse admin client.

    Используется в admin endpoints ``admin_workflow_audit.py`` и
    ``admin_workflow_cost.py`` вместо inline ``get_async_client()``.

    Returns:
        AsyncClient instance (clickhouse_connect).

    Note:
        При ошибке подключения возвращает None — endpoints должны
        обрабатывать None gracefully (fallback к in-memory state).
    """
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
        return await get_async_client(host=host, port=port, database=database)
    except Exception as exc:
        _logger.warning("ClickHouse admin client unavailable: %s", exc)
        return None
