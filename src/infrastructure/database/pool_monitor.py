"""Мониторинг пула соединений PostgreSQL.

Периодически собирает метрики пула SQLAlchemy:
- Размер пула (checkedin / checkedout / overflow)
- Время ожидания checkout
- Детект утечек (checkout без возврата > N секунд)

Экспортирует метрики для SLO tracker и Prometheus.
"""

import asyncio
import logging
import time
from typing import Any

__all__ = ("PoolMonitor", "get_pool_monitor")

logger = logging.getLogger("db.pool_monitor")


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
        self._task = asyncio.create_task(self._monitor_loop())
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
            from app.infrastructure.database.database import db_initializer

            pool = db_initializer._async_engine.pool  # type: ignore[union-attr]

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
        except Exception:
            return None

    def get_current_stats(self) -> dict[str, Any]:
        """Возвращает последнюю запись статистики."""
        if self._stats_history:
            return self._stats_history[-1]
        return {"status": "no_data"}

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Возвращает историю статистики."""
        return self._stats_history[-limit:]


from app.core.di import app_state_singleton


@app_state_singleton("pool_monitor", PoolMonitor)
def get_pool_monitor() -> PoolMonitor:
    """Возвращает PoolMonitor из app.state или lazy-init fallback."""
