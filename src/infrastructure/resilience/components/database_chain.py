"""Wiring W26.4: PostgreSQL → SQLite read-only.

Контракт callable: ``async def db_query(sql: str, params: dict | None = None) -> list[dict]``.

Read-only операции. При OPEN-breaker'е coordinator переключается на
SQLite-snapshot (генерируется отдельным background-job'ом из PG dumps).

Write-операции в fallback-режиме блокируются на FastAPI middleware-
уровне (см. W26.5 — ``DegradationMiddleware``): возвращается HTTP 503
``Retry-After``, чтобы клиент попробовал позже.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

__all__ = (
    "DBQueryCallable",
    "build_database_fallbacks",
    "build_database_primary",
)

logger = logging.getLogger(__name__)

DBQueryCallable = Callable[[str, dict[str, Any] | None], Awaitable[list[dict[str, Any]]]]


async def _pg_query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from src.infrastructure.database.database import get_db_session

    async with get_db_session() as session:
        result = await session.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result.fetchall()]


_sqlite_engine = None


def _get_sqlite_engine():
    """Lazy-init SQLite read-only engine."""
    global _sqlite_engine
    if _sqlite_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        snapshot_path = Path("var/db/snapshot.sqlite")
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot_path.exists():
            snapshot_path.touch()
        # mode=ro гарантирует, что любые INSERT/UPDATE/DELETE упадут.
        url = f"sqlite+aiosqlite:///{snapshot_path}?mode=ro&uri=true"
        _sqlite_engine = create_async_engine(url, future=True)
    return _sqlite_engine


async def _sqlite_ro_query(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    engine = _get_sqlite_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result.fetchall()]


def build_database_primary() -> DBQueryCallable:
    return _pg_query


def build_database_fallbacks() -> dict[str, DBQueryCallable]:
    return {"sqlite_ro": _sqlite_ro_query}
