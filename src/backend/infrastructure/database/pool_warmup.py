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
import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.tenancy import current_tenant
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("PoolReconnectMonitor", "PoolWarmup", "WarmupResult")

logger = get_logger(__name__)

#: Sentinel tenant label для startup-метрик (lifespan) когда TenantContext
#: ещё не установлен (нет request handler). Отличается от tenant_id=None для
#: Prometheus dashboards: '_global_' = shared/system, None = unknown/missing.
_TENANT_GLOBAL: str = "_global_"


def _current_tenant_label() -> str:
    """Возвращает tenant_id из TenantContext contextvar или ``_global_``.

    Используется как Prometheus label value. Sentinel ``_global_`` для
    lifespan/warmup-операций, которые происходят до request handler
    (нет tenant context).
    """
    try:
        ctx = current_tenant()
    except Exception:  # noqa: BLE001 — best-effort metric label
        return _TENANT_GLOBAL
    if ctx is None or not getattr(ctx, "tenant_id", None):
        return _TENANT_GLOBAL
    return str(ctx.tenant_id)


try:  # pragma: no cover - prometheus_client optional
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Histogram as _PromHistogram

    _WARMUP_DURATION = _PromHistogram(
        "pool_warmup_duration_ms",
        "Pool warmup duration in milliseconds",
        ("pool", "tenant_id"),
    )
    _WARMUP_FAILURES = _PromCounter(
        "pool_warmup_failures_total", "Pool warmup failures", ("pool", "tenant_id")
    )
    _POOL_RECONNECTS = _PromCounter(
        "pool_reconnects_total", "Pool reconnect events", ("pool", "tenant_id")
    )
except Exception as _:
    _WARMUP_DURATION = None  # type: ignore[assignment,unused-ignore]
    _WARMUP_FAILURES = None  # type: ignore[assignment,unused-ignore]
    _POOL_RECONNECTS = None  # type: ignore[assignment,unused-ignore]


def _record_warmup(pool: str, duration_ms: float, success: bool) -> None:
    tenant_label = _current_tenant_label()
    if _WARMUP_DURATION is not None:
        try:
            _WARMUP_DURATION.labels(pool=pool, tenant_id=tenant_label).observe(
                duration_ms
            )
        except Exception:
            pass
    if not success and _WARMUP_FAILURES is not None:
        try:
            _WARMUP_FAILURES.labels(pool=pool, tenant_id=tenant_label).inc()
        except Exception:
            pass


def _record_reconnect(pool: str) -> None:
    tenant_label = _current_tenant_label()
    if _POOL_RECONNECTS is not None:
        try:
            _POOL_RECONNECTS.labels(pool=pool, tenant_id=tenant_label).inc()
        except Exception:
            pass


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

        from src.backend.core.utils.task_registry import get_task_registry

        registry = get_task_registry()
        if self._pg is not None:
            tasks["pg"] = registry.create_task(self._warmup_pg(), name="pool-warmup-pg")
        if self._pg_replica is not None:
            tasks["pg_replica"] = registry.create_task(
                self._warmup_pg_replica(), name="pool-warmup-pg-replica"
            )
        if self._redis is not None:
            tasks["redis"] = registry.create_task(
                self._warmup_redis(), name="pool-warmup-redis"
            )
        if self._ch is not None:
            tasks["clickhouse"] = registry.create_task(
                self._warmup_clickhouse(), name="pool-warmup-clickhouse"
            )

        if not tasks:
            return result

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks.values(), return_exceptions=True),
                timeout=self._timeout,
            )
        except TimeoutError:
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
        from sqlalchemy import text  # type: ignore[import-untyped,unused-ignore]

        # min_connections параллельных SELECT 1 — заставляет SQLAlchemy
        # открыть требуемое число соединений в пуле.
        async def _ping() -> None:
            async with self._pg.begin() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(*(_ping() for _ in range(self._min)))

    async def _warmup_pg_replica(self) -> None:
        from sqlalchemy import text  # type: ignore[import-untyped,unused-ignore]

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

    async def warmup_httpx(
        self,
        client: Any,
        target_url: str,
        *,
        min_connections: int = 3,
        timeout_seconds: float = 5.0,
    ) -> WarmupResult:
        """Прогреть HTTPX OutboundHttpClient серией HEAD-запросов (S13 K2 W7).

        Args:
            client: ``OutboundHttpClient`` или ``httpx.AsyncClient`` с ``head()``.
            target_url: URL для прогрева (рекомендуется ``/health`` целевого сервиса).
            min_connections: Целевое число одновременных соединений (default 3).
            timeout_seconds: Max time на прогрев.
        """
        start = time.monotonic()
        result = WarmupResult()

        async def _ping() -> None:
            await client.head(target_url, timeout=timeout_seconds)

        try:
            await asyncio.wait_for(
                asyncio.gather(*(_ping() for _ in range(min_connections))),
                timeout=timeout_seconds,
            )
            result.warmed_pools.append("httpx")
            _record_warmup("httpx", (time.monotonic() - start) * 1000, success=True)
        except Exception as exc:
            result.failed_pools["httpx"] = type(exc).__name__
            _record_warmup("httpx", (time.monotonic() - start) * 1000, success=False)
            logger.warning(
                "pool_warmup.httpx_failed",
                extra={"target": target_url, "error_class": type(exc).__name__},
            )

        result.duration_seconds = time.monotonic() - start
        return result

    async def warmup_graylog(
        self, sink: Any, *, ping_count: int = 3, timeout_seconds: float = 3.0
    ) -> WarmupResult:
        """Прогреть Graylog TCP-pool серией keepalive GELF-чанков (S13 K2 W7).

        Args:
            sink: GraylogSink с методом ``async def emit_keepalive()`` или
                ``async def emit({"_keepalive": True})``.
            ping_count: Сколько keepalive-сообщений отправить.
            timeout_seconds: Max time на прогрев.
        """
        start = time.monotonic()
        result = WarmupResult()

        async def _ping() -> None:
            if hasattr(sink, "emit_keepalive"):
                await sink.emit_keepalive()
            else:
                await sink.emit({"_keepalive": True, "_warmup": True})

        try:
            await asyncio.wait_for(
                asyncio.gather(*(_ping() for _ in range(ping_count))),
                timeout=timeout_seconds,
            )
            result.warmed_pools.append("graylog")
            _record_warmup("graylog", (time.monotonic() - start) * 1000, success=True)
        except Exception as exc:
            result.failed_pools["graylog"] = type(exc).__name__
            _record_warmup("graylog", (time.monotonic() - start) * 1000, success=False)
            logger.warning(
                "pool_warmup.graylog_failed", extra={"error_class": type(exc).__name__}
            )

        result.duration_seconds = time.monotonic() - start
        return result


class PoolReconnectMonitor:
    """Фоновая задача, мониторит health пулов и переинициализирует при reconnect (S13 K2 W7).

    Args:
        pools: Dict ``{"name": healthcheck_callable}``. Callable должен быть
            async и возвращать True (healthy) / False (unhealthy).
        on_reconnect: Async callback, вызывается при disconnect detection.
        interval_seconds: Период между проверками (default 30s).
    """

    def __init__(
        self,
        pools: dict[str, Any],
        *,
        on_reconnect: Any = None,
        interval_seconds: float = 30.0,
    ) -> None:
        self._pools = pools
        self._on_reconnect = on_reconnect
        self._interval = interval_seconds
        self._last_state: dict[str, bool] = dict.fromkeys(pools, True)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._loop(), name="pool_reconnect_monitor"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError, Exception:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            if self._stop_event.is_set():
                return
            for name, healthcheck in self._pools.items():
                try:
                    healthy = await healthcheck()
                except Exception as _:
                    healthy = False
                previously_healthy = self._last_state.get(name, True)
                if not healthy and previously_healthy:
                    logger.warning(
                        "pool_reconnect_monitor.unhealthy", extra={"pool": name}
                    )
                    self._last_state[name] = False
                elif healthy and not previously_healthy:
                    logger.info(
                        "pool_reconnect_monitor.reconnected", extra={"pool": name}
                    )
                    _record_reconnect(name)
                    self._last_state[name] = True
                    if self._on_reconnect is not None:
                        try:
                            await self._on_reconnect(name)
                        except Exception as _:
                            logger.exception("pool_reconnect_monitor.callback_failed")
