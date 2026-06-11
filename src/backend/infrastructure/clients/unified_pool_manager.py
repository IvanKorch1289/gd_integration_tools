"""UnifiedPoolManager — центральный реестр и оркестратор всех connection pools.

Назначение (S37.2):
    Агрегирует существующие пулы (DB, Redis, Kafka, ClickHouse, NATS, HTTPX,
    SMTP, IMAP) в единой точке.  Предоставляет:

    * ``register()`` / ``unregister()`` — добавление/удаление пула по имени.
    * ``get_metrics()`` — сбор метрик со всех зарегистрированных пулов.
    * ``health_check_all()`` — параллельный health-check всех пулов.
    * ``warmup_all()`` — прогрев всех пулов (обёртка над ``PoolWarmup``).
    * ``start_monitors()`` / ``stop_monitors()`` — запуск/остановка фоновых
      ``PoolHealthMonitor`` + ``PoolMonitor``.

    Интегрирует существующие компоненты без дублирования:
    ``PoolHealthMonitor``, ``ConnectionReuseManager``, ``PoolMetricsCollector``,
    ``PoolWarmup``, ``PoolMonitor``.

Использование::

    manager = get_unified_pool_manager()
    manager.register("db_main", db_engine.pool, ping_fn=ping_db)
    manager.register("redis_cache", redis_client, ping_fn=ping_redis)
    await manager.start_monitors()
    metrics = await manager.get_metrics()
    health = await manager.health_check_all(mode="fast")
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("PoolRegistration", "UnifiedPoolManager", "get_unified_pool_manager")

logger = get_logger("infrastructure.clients.unified_pool_manager")


@dataclass
class PoolRegistration:
    """Описание одного зарегистрированного пула.

    Attributes:
        name: Уникальное логическое имя.
        pool: Объект пула (SQLAlchemy Pool, redis-py client, httpx client, …).
        ping_fn: Async callable без аргументов для проверки «живости».
        kind: Тип пула ("sqlalchemy", "redis", "kafka", "clickhouse",
            "nats", "httpx", "smtp", "imap", …).
        max_size: Максимальный размер пула (для метрик).
    """

    name: str
    pool: Any
    ping_fn: Callable[[], Awaitable[Any]]
    kind: str = "unknown"
    max_size: int = 0


class UnifiedPoolManager:
    """Центральный реестр всех backend connection pools.

    Thread-safe для чтения/записи в рамках одного event-loop
    (asyncio-контекст).  Не создаёт background-задач при инициализации —
    явный вызов ``start_monitors()`` из lifespan.
    """

    def __init__(self) -> None:
        self._pools: dict[str, PoolRegistration] = {}
        self._started: bool = False

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        pool: Any,
        *,
        ping_fn: Callable[[], Awaitable[Any]],
        kind: str = "unknown",
        max_size: int = 0,
    ) -> None:
        """Регистрирует пул в едином реестре.

        Повторный вызов с тем же ``name`` перезаписывает запись.
        Регистрация безопасна до ``start_monitors()``.
        """
        self._pools[name] = PoolRegistration(
            name=name, pool=pool, ping_fn=ping_fn, kind=kind, max_size=max_size
        )
        logger.debug("UnifiedPoolManager: зарегистрирован '%s' (%s)", name, kind)

    def unregister(self, name: str) -> None:
        """Удаляет пул из реестра."""
        self._pools.pop(name, None)
        logger.debug("UnifiedPoolManager: удалён '%s'", name)

    def list_pools(self) -> list[str]:
        """Возвращает список имён зарегистрированных пулов."""
        return sorted(self._pools.keys())

    # ------------------------------------------------------------------
    # Метрики
    # ------------------------------------------------------------------

    async def get_metrics(self) -> dict[str, dict[str, Any]]:
        """Собирает метрики со всех зарегистрированных пулов.

        Для SQLAlchemy-пулов использует ``PoolMonitor``-статистику.
        Для остальных — best-effort (idle/active/total если доступно).
        """
        result: dict[str, dict[str, Any]] = {}
        for name, reg in self._pools.items():
            metrics: dict[str, Any] = {"kind": reg.kind, "max_size": reg.max_size}
            pool = reg.pool

            # SQLAlchemy AsyncEngine.pool
            if reg.kind == "sqlalchemy" and hasattr(pool, "size"):
                try:
                    metrics.update(
                        {
                            "size": pool.size(),
                            "checked_in": pool.checkedin(),
                            "checked_out": pool.checkedout(),
                            "overflow": pool.overflow(),
                            "utilization_pct": round(
                                (pool.checkedout() / max(pool.size(), 1)) * 100, 1
                            ),
                        }
                    )
                except Exception as exc:
                    metrics["error"] = str(exc)[:100]

            # redis-py
            elif reg.kind == "redis" and hasattr(pool, "connection_pool"):
                cp = pool.connection_pool
                try:
                    metrics.update(
                        {
                            "available": getattr(cp, "available_connections", 0),
                            "in_use": getattr(cp, "in_use_connections", 0),
                        }
                    )
                except Exception as exc:
                    metrics["error"] = str(exc)[:100]

            # httpx Limits
            elif reg.kind == "httpx" and hasattr(pool, "limits"):
                try:
                    limits = pool.limits
                    metrics.update(
                        {
                            "max_connections": limits.max_connections,
                            "max_keepalive": limits.max_keepalive_connections,
                        }
                    )
                except Exception as exc:
                    metrics["error"] = str(exc)[:100]

            # Generic fallback
            else:
                for attr in ("size", "maxsize", "available", "in_use", "idle"):
                    if hasattr(pool, attr):
                        try:
                            metrics[attr] = getattr(pool, attr)
                        except Exception:
                            pass

            result[name] = metrics
        return result

    # ------------------------------------------------------------------
    # Health-check
    # ------------------------------------------------------------------

    async def health_check_all(
        self, *, mode: str = "fast", timeout: float = 2.5
    ) -> dict[str, Any]:
        """Параллельный health-check всех зарегистрированных пулов.

        Args:
            mode: ``"fast"`` (<100ms) или ``"deep"`` (<2s).
            timeout: SLA-timeout на один пул (сек).

        Returns:
            dict вида::

                {
                    "status": "ok" | "degraded" | "down",
                    "pools": {
                        "db_main": {"status": "ok", "latency_ms": 3.2},
                        ...
                    }
                }
        """

        async def _check_one(name: str, reg: PoolRegistration) -> dict[str, Any]:
            start = time.monotonic()
            try:
                await asyncio.wait_for(reg.ping_fn(), timeout=timeout)
                latency_ms = round((time.monotonic() - start) * 1000, 2)
                return {"status": "ok", "latency_ms": latency_ms}
            except asyncio.TimeoutError:
                return {
                    "status": "error",
                    "error": f"timeout after {timeout}s",
                    "latency_ms": timeout * 1000,
                }
            except Exception as exc:
                latency_ms = round((time.monotonic() - start) * 1000, 2)
                return {
                    "status": "error",
                    "error": str(exc)[:200],
                    "latency_ms": latency_ms,
                }

        async with asyncio.TaskGroup() as tg:
            tasks = {
                name: tg.create_task(_check_one(name, reg))
                for name, reg in self._pools.items()
            }

        pools_result: dict[str, dict[str, Any]] = {}
        overall = "ok"
        for name, t in tasks.items():
            comp = t.result()
            pools_result[name] = comp
            status = comp.get("status", "unknown")
            if status == "error":
                overall = "down"
            elif status in ("degraded", "unknown") and overall == "ok":
                overall = "degraded"

        return {
            "status": overall,
            "mode": mode,
            "pools": pools_result,
            "registered": len(self._pools),
        }

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    async def warmup_all(self) -> dict[str, str]:
        """Прогрев всех зарегистрированных пулов.

        Делегирует в ``PoolWarmup`` если он доступен, иначе —
        выполняет простой ``ping_fn()`` для каждого пула.

        Returns:
            dict ``name -> "ok" | "skipped" | "error: …"``.
        """
        result: dict[str, str] = {}
        try:
            from src.backend.infrastructure.database.pool_warmup import PoolWarmup

            warmup = PoolWarmup()
            for name, reg in self._pools.items():
                try:
                    if reg.kind == "sqlalchemy":
                        await warmup.warmup_postgres(reg.pool)
                    elif reg.kind == "redis":
                        await warmup.warmup_redis(reg.pool)
                    else:
                        await reg.ping_fn()
                    result[name] = "ok"
                except Exception as exc:
                    result[name] = f"error: {exc}"[:100]
        except ImportError:
            # PoolWarmup недоступен — fallback на простой ping
            for name, reg in self._pools.items():
                try:
                    await reg.ping_fn()
                    result[name] = "ok"
                except Exception as exc:
                    result[name] = f"error: {exc}"[:100]
        return result

    # ------------------------------------------------------------------
    # Lifecycle (мониторы)
    # ------------------------------------------------------------------

    async def start_monitors(self) -> None:
        """Запускает фоновые мониторы: ``PoolHealthMonitor`` + ``PoolMonitor``.

        Безопасен для повторного вызова (no-op если уже запущены).
        Регистрирует все известные пулы в ``PoolHealthMonitor`` перед стартом.
        """
        if self._started:
            return
        self._started = True

        # 1. PoolHealthMonitor — idle-ping для всех пулов
        try:
            from src.backend.infrastructure.clients.pool_health import get_pool_monitor

            monitor = get_pool_monitor()
            for name, reg in self._pools.items():
                monitor.register_pool(
                    name=name,
                    pool=reg.pool,
                    ping_callable=reg.ping_fn,
                    idle_timeout=60.0,
                )
            await monitor.start()
        except Exception as exc:
            logger.warning("UnifiedPoolManager: PoolHealthMonitor не запущен: %s", exc)

        # 2. PoolMonitor — SQLAlchemy-специфичные метрики
        try:
            from src.backend.infrastructure.database.pool_monitor import (
                get_pool_monitor as get_db_pool_monitor,
            )

            db_monitor = get_db_pool_monitor()
            await db_monitor.start()
        except Exception as exc:
            logger.warning("UnifiedPoolManager: PoolMonitor не запущен: %s", exc)

        logger.info(
            "UnifiedPoolManager: мониторы запущены (pools=%d)", len(self._pools)
        )

    async def stop_monitors(self) -> None:
        """Останавливает фоновые мониторы."""
        self._started = False
        try:
            from src.backend.infrastructure.clients.pool_health import get_pool_monitor

            await get_pool_monitor().stop()
        except Exception as exc:
            logger.debug("UnifiedPoolManager: stop pool_health_monitor: %s", exc)

        try:
            from src.backend.infrastructure.database.pool_monitor import (
                get_pool_monitor as get_db_pool_monitor,
            )

            await get_db_pool_monitor().stop()
        except Exception as exc:
            logger.debug("UnifiedPoolManager: stop db_pool_monitor: %s", exc)

        logger.info("UnifiedPoolManager: мониторы остановлены")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager_instance: UnifiedPoolManager | None = None


def get_unified_pool_manager() -> UnifiedPoolManager:
    """Возвращает singleton UnifiedPoolManager.

    Lazy-init; не создаёт background-задач.
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = UnifiedPoolManager()
    return _manager_instance
