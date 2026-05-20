"""Pool warm-up — pre-spin connection pools в lifespan (Sprint 9 K2 W3).

Цель: убрать cold-start latency на первый запрос. До warm-up:

* SQLAlchemy lazy создаёт connection на первый ``begin()`` (~50-100ms);
* Redis ``aioredis`` не открывает TCP до первого вызова;
* ClickHouse HTTP-pool пуст до первого insert.

После warm-up: ``min_connections`` соединений уже открыты в startup.

Использование в lifespan (см. :mod:`plugins.composition.lifecycle`):

.. code-block:: python

    await PoolWarmup(
        pg_engine=engine,
        redis_client=redis,
        clickhouse_client=ch,
        min_connections=3,
    ).warmup()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PoolWarmup", "WarmupResult")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WarmupResult:
    """Метрики прогрева для health-check и Prometheus.

    Attributes:
        duration_seconds: общее время прогрева.
        warmed_pools: какие пулы успешно прогреты ("pg", "redis", "ch").
        failed_pools: пулы, которые упали с exception (degraded mode).
    """

    duration_seconds: float = 0.0
    warmed_pools: list[str] = field(default_factory=list)
    failed_pools: dict[str, str] = field(default_factory=dict)


class PoolWarmup:
    """Pre-spin connection pools в startup.

    Args:
        pg_engine: optional SQLAlchemy AsyncEngine (если None — skip PG).
        redis_client: optional Redis client с .ping() метод.
        clickhouse_client: optional ClickHouse client с .execute("SELECT 1").
        min_connections: целевое число соединений per pool (default 3).
        timeout_seconds: max time на warmup (default 5s).
    """

    def __init__(
        self,
        *,
        pg_engine: Any = None,
        pg_replica_engine: Any = None,
        redis_client: Any = None,
        clickhouse_client: Any = None,
        min_connections: int = 3,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._pg = pg_engine
        self._pg_replica = pg_replica_engine
        self._redis = redis_client
        self._ch = clickhouse_client
        self._min = min_connections
        self._timeout = timeout_seconds

    async def warmup(self) -> WarmupResult:
        """Прогреть все доступные пулы параллельно.

        Returns:
            :class:`WarmupResult` с метриками. Никогда не raise — если
            пул упал, информация в ``failed_pools``.
        """
        start = time.monotonic()
        result = WarmupResult()
        tasks: dict[str, asyncio.Task[None]] = {}

        if self._pg is not None:
            tasks["pg"] = asyncio.create_task(self._warmup_pg())
        if self._pg_replica is not None:
            tasks["pg_replica"] = asyncio.create_task(self._warmup_pg_replica())
        if self._redis is not None:
            tasks["redis"] = asyncio.create_task(self._warmup_redis())
        if self._ch is not None:
            tasks["clickhouse"] = asyncio.create_task(self._warmup_clickhouse())

        if not tasks:
            return result

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "pool_warmup.timeout",
                extra={"timeout_seconds": self._timeout, "min": self._min},
            )

        for name, task in tasks.items():
            if task.cancelled() or not task.done():
                result.failed_pools[name] = "timeout"
                continue
            exc = task.exception()
            if exc is None:
                result.warmed_pools.append(name)
            else:
                result.failed_pools[name] = type(exc).__name__
                logger.warning(
                    "pool_warmup.pool_failed",
                    extra={"pool": name, "error_class": type(exc).__name__},
                )

        result.duration_seconds = time.monotonic() - start
        logger.info(
            "pool_warmup.done",
            extra={
                "duration_seconds": result.duration_seconds,
                "warmed": result.warmed_pools,
                "failed": list(result.failed_pools.keys()),
            },
        )
        return result

    async def _warmup_pg(self) -> None:
        from sqlalchemy import text  # type: ignore[import-untyped]

        # min_connections параллельных SELECT 1 — заставляет SQLAlchemy
        # открыть требуемое число соединений в пуле.
        async def _ping() -> None:
            async with self._pg.begin() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(*(_ping() for _ in range(self._min)))

    async def _warmup_pg_replica(self) -> None:
        from sqlalchemy import text  # type: ignore[import-untyped]

        async def _ping() -> None:
            async with self._pg_replica.begin() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(*(_ping() for _ in range(self._min)))

    async def _warmup_redis(self) -> None:
        async def _ping() -> None:
            await self._redis.ping()

        await asyncio.gather(*(_ping() for _ in range(self._min)))

    async def _warmup_clickhouse(self) -> None:
        async def _ping() -> None:
            await self._ch.execute("SELECT 1")

        await asyncio.gather(*(_ping() for _ in range(self._min)))
