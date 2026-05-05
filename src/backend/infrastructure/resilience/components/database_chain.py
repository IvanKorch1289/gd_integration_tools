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

__all__ = ("DBQueryCallable", "build_database_fallbacks", "build_database_primary")

logger = logging.getLogger(__name__)

DBQueryCallable = Callable[
    [str, dict[str, Any] | None], Awaitable[list[dict[str, Any]]]
]


async def _pg_query(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from src.backend.infrastructure.database.database import get_db_session

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


_stale_warning_counter: Any = None


def _ensure_stale_metric() -> None:
    """Lazy-init Prometheus-counter'а stale-fallback'ов."""
    global _stale_warning_counter
    if _stale_warning_counter is not None:
        return
    try:
        from prometheus_client import Counter

        _stale_warning_counter = Counter(
            "db_fallback_used_with_stale_snapshot_total",
            "Times db_main fallback returned data from a stale snapshot",
        )
    except ImportError:
        return


def _check_snapshot_freshness() -> None:
    """Логирует degraded-confidence, если snapshot устарел.

    Не блокирует запрос: при stale-snapshot'е fallback всё равно
    возвращает данные (лучше stale, чем 503). Но операторы должны
    видеть ситуацию — поэтому warning + Prometheus counter.
    """
    try:
        from src.backend.core.config.settings import settings
        from src.backend.infrastructure.resilience.snapshot_job import (
            get_snapshot_age_seconds,
            is_snapshot_fresh,
        )

        threshold = settings.snapshot.fresh_threshold_seconds
        if is_snapshot_fresh(threshold):
            return

        age = get_snapshot_age_seconds()
        age_repr = f"{age:.0f}s" if age is not None else "never"
        logger.warning(
            "STALE snapshot, returning anyway with degraded confidence "
            "(age=%s, threshold=%ds)",
            age_repr,
            threshold,
        )
        _ensure_stale_metric()
        if _stale_warning_counter is not None:
            _stale_warning_counter.inc()
    except Exception as exc:  # noqa: BLE001
        # Snapshot-job или метрики могут быть недоступны (dev_light/тесты);
        # не ломаем fallback из-за вспомогательной телеметрии.
        logger.debug("Snapshot freshness check skipped: %s", exc)


async def _sqlite_ro_query(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    _check_snapshot_freshness()

    engine = _get_sqlite_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result.fetchall()]


def build_database_primary() -> DBQueryCallable:
    return _pg_query


def build_database_fallbacks() -> dict[str, DBQueryCallable]:
    return {"sqlite_ro": _sqlite_ro_query}
