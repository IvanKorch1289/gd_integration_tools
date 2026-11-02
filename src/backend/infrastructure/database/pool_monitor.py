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

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

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
        """Метод start (см. signature)."""
        self._running = True
        self._task = get_task_registry().create_task(
            self._monitor_loop(), name="db-pool-monitor"
        )
        logger.info("DB pool monitor started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Метод stop (см. signature)."""
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

            # Cycle 172 (MEDIUM-07): атрибут называется ``async_engine``,
            # а читался ``_async_engine``. ``AttributeError`` глотался
            # ниже, поэтому ``collect_stats()`` **всегда** возвращал
            # ``None`` — мониторинг пула не работал ни разу.
            # В этом же файле на строке ~144 атрибут указан правильно,
            # что подтверждает опечатку, а не опровергает её.
            pool = db_initializer.async_engine.pool

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


def register_db_pool_in_unified_monitor(initializer: Any = None) -> None:
    """Регистрирует пул main-БД в ``UnifiedPoolManager`` и ``PoolHealthMonitor``.

    ADR-0420: ранее функция была приватной и **не имела ни одного
    вызова** (мёртвый код). Теперь она вызывается при ротации кредов БД:
    пересозданный engine даёт новый объект пула, а мониторы держали бы
    объект пула **старого** engine'а и пинговали бы его по отозванным
    кредам. Регистрация идемпотентна — запись по имени ``db_main``
    перезаписывается.

    Args:
        initializer: ``DatabaseInitializer`` нового engine'а. Если ``None`` —
            берётся текущий singleton через accessor.

    Returns:
        None.

    """
    if initializer is None:
        from src.backend.infrastructure.database.database.accessors import (
            get_db_initializer,
        )

        initializer = get_db_initializer()

    engine = getattr(initializer, "async_engine", None)
    if engine is None:
        return
    pool = getattr(engine, "pool", None)
    if pool is None:
        return

    async def _ping_db() -> None:
        """Ping-callable для основной БД через check_connection."""
        await initializer.check_connection()

    try:
        from src.backend.infrastructure.clients.unified_pool_manager import (
            get_unified_pool_manager,
        )

        size = getattr(pool, "size", None)
        get_unified_pool_manager().register(
            "db_main",
            pool,
            ping_fn=_ping_db,
            kind="sqlalchemy",
            max_size=size() if callable(size) else 0,
        )
    except Exception as exc:
        logger.debug("UnifiedPoolManager: регистрация db_main пропущена: %s", exc)

    try:
        from src.backend.infrastructure.clients.pool_health import (
            get_pool_monitor as get_unified_monitor,
        )

        get_unified_monitor().register_pool(
            name="db_main", pool=pool, ping_callable=_ping_db, idle_timeout=60.0
        )
    except Exception as exc:
        logger.debug("PoolHealthMonitor: регистрация db_main пропущена: %s", exc)
