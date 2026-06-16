"""Мониторинг пула соединений PostgreSQL.

Периодически собирает метрики пула SQLAlchemy:
- Размер пула (checkedin / checkedout / overflow)
- Время ожидания checkout
- Детект утечек (checkout без возврата > N секунд)

Экспортирует метрики для SLO tracker и Prometheus.
"""

import asyncio
import time
from typing import Any

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("PoolMonitor", "get_pool_monitor")

logger = get_logger("db.pool_monitor")


class PoolMonitor:
    """Мониторинг пула соединений базы данных."""

    def __init__(self, check_interval: int = 30) -> None:
        self._interval = check_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._stats_history: list[dict[str, Any]] = []
        self._max_history = 1000

    async def start(self) -> None:
        self._running = True
        self._task = get_task_registry().create_task(
            self._monitor_loop(), name="db-pool-monitor"
        )
        logger.info("DB pool monitor started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                stats = await self.collect_stats()
                if stats:
                    self._stats_history.append(stats)
                    if len(self._stats_history) > self._max_history:
                        self._stats_history = self._stats_history[-500:]

                    utilization = stats.get("utilization_pct", 0)
                    if utilization > 80:
                        logger.warning(
                            "DB pool utilization HIGH: %.1f%% (checked_out=%d, pool_size=%d)",
                            utilization,
                            stats.get("checked_out", 0),
                            stats.get("pool_size", 0),
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Pool monitor error: %s", exc)

            await asyncio.sleep(self._interval)

    async def collect_stats(self) -> dict[str, Any] | None:
        """Собирает текущую статистику пула."""
        try:
            from src.backend.infrastructure.database.database import db_initializer

            pool = db_initializer._async_engine.pool

            checked_in = pool.checkedin()
            checked_out = pool.checkedout()
            overflow = pool.overflow()
            pool_size = pool.size()
            total = checked_in + checked_out

            utilization = (checked_out / max(pool_size, 1)) * 100

            return {
                "timestamp": time.time(),
                "pool_size": pool_size,
                "checked_in": checked_in,
                "checked_out": checked_out,
                "overflow": overflow,
                "total_connections": total,
                "utilization_pct": round(utilization, 1),
            }
        except AttributeError, TypeError:
            return None

    def get_current_stats(self) -> dict[str, Any]:
        """Возвращает последнюю запись статистики."""
        if self._stats_history:
            return self._stats_history[-1]
        return {"status": "no_data"}

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Возвращает историю статистики."""
        return self._stats_history[-limit:]


from src.backend.core.di import app_state_singleton


@app_state_singleton("pool_monitor", PoolMonitor)
def get_pool_monitor() -> PoolMonitor:  # type: ignore[empty-body]
    """Возвращает PoolMonitor из app.state или lazy-init fallback."""


def _register_db_pool_in_unified_monitor() -> None:
    """Spike-регистрация DB pool в едином PoolHealthMonitor (K8 W5).

    Демонстрирует паттерн подключения существующего pool к
    PoolHealthMonitor из infrastructure.clients.pool_health.

    Вызывается из lifespan при наличии db_initializer.
    Безопасна при отключённом feature-flag (monitor.start() — no-op).
    """
    try:
        from src.backend.infrastructure.clients.pool_health import (
            get_pool_monitor as get_unified_monitor,
        )
        from src.backend.infrastructure.database.database import get_db_initializer

        db_init = get_db_initializer()

        async def _ping_db() -> None:
            """Ping-callable для основной БД через check_connection."""
            await db_init.check_connection()

        get_unified_monitor().register_pool(
            name="db_main",
            pool=db_init.async_engine.pool,
            ping_callable=_ping_db,
            idle_timeout=60.0,
        )
    except Exception as exc:
        logger.debug("Spike DB pool registration пропущена: %s", exc)
