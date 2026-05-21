"""Единый health-monitor для всех backend connection pools.

Назначение:
    Централизованный фоновый компонент, реализующий V15 R-V15-14:
    idle-ping + reuse-on-demand для DB / Redis / HTTP пулов.

    Запускается как background-task через TaskRegistry (V15 R-V15-11)
    только при включённом feature-flag ``pool_health_monitor``.
    При default-OFF flag не создаёт ни фоновой задачи, ни соединений —
    абсолютно нулевой overhead для окружений без флага.

Использование::

    monitor = get_pool_monitor()
    monitor.register_pool(
        name="db_main",
        pool=db_engine.pool,
        ping_callable=ping_db,
        idle_timeout=60.0,
    )
    await monitor.start()   # вызывается из lifespan при flag ON
    ...
    await monitor.stop()    # при shutdown

Интеграция:
    Spike-регистрация через ``infrastructure.database.pool_monitor``
    демонстрирует паттерн подключения. Полное покрытие всех pool'ов —
    в последующих Wave по мере включения flag.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PoolEntry", "PoolHealthMonitor", "get_pool_monitor")

logger = logging.getLogger("infrastructure.clients.pool_health")


# ---------------------------------------------------------------------------
# Вспомогательный тип: описание зарегистрированного pool'а
# ---------------------------------------------------------------------------


@dataclass
class PoolEntry:
    """Запись об одном зарегистрированном backend-пуле.

    Attributes:
        name: Логическое имя пула (например ``"db_main"``).
        pool: Объект пула (любой тип; не используется напрямую).
        ping_callable: Async-callable без аргументов; возвращает любой
            тип. Ошибка при вызове логируется и НЕ прерывает monitor-loop.
        idle_timeout: Минимальное время простоя (секунды), после которого
            выполняется ping. По умолчанию 60 секунд.
        last_ping_at: Метка времени последнего успешного/попытного пинга.
    """

    name: str
    pool: Any
    ping_callable: Callable[[], Awaitable[Any]]
    idle_timeout: float = 60.0
    last_ping_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Основной monitor
# ---------------------------------------------------------------------------


class PoolHealthMonitor:
    """Единый health-monitor для backend connection pools.

    Периодически (каждые ``tick_interval`` секунд) проверяет зарегистрированные
    пулы: если время с последнего пинга превысило ``idle_timeout`` — вызывает
    ``ping_callable``. Это предотвращает разрыв idle-соединений на стороне
    сервера и реализует паттерн «reuse-on-demand» (V15 R-V15-14).

    Lifecycle::

        monitor = get_pool_monitor()
        monitor.register_pool("db", engine.pool, ping_db)
        await monitor.start()   # в lifespan при feature_flag ON
        ...
        await monitor.stop()    # при shutdown (зеркальный порядок)

    Singleton:
        Используется через :func:`get_pool_monitor`. Один экземпляр на
        процесс, хранится в модульной переменной.

    Attributes:
        tick_interval: Период фоновой итерации (секунды).
        _pools: Словарь зарегистрированных пулов по имени.
        _task: Ссылка на background-asyncio.Task (или None).
        _running: Флаг активности monitor-loop.
    """

    def __init__(self, tick_interval: float = 30.0) -> None:
        """Инициализирует monitor.

        Args:
            tick_interval: Период между итерациями monitor-loop (сек).
        """
        self.tick_interval = tick_interval
        self._pools: dict[str, PoolEntry] = {}
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_pool(
        self,
        name: str,
        pool: Any,
        ping_callable: Callable[[], Awaitable[Any]],
        idle_timeout: float = 60.0,
    ) -> None:
        """Регистрирует pool с кастомным ping-callable.

        Повторный вызов с тем же именем перезаписывает запись
        (идемпотентен). Регистрацию можно выполнять до вызова
        :meth:`start` — пулы накапливаются.

        Args:
            name: Логическое имя пула (уникальный ключ).
            pool: Объект пула; хранится для справки, не используется напрямую.
            ping_callable: Async-callable без аргументов; должен подключаться
                к backend и возвращать любое значение (или raise при ошибке).
            idle_timeout: Порог idle-времени (сек) перед очередным пингом.
        """
        self._pools[name] = PoolEntry(
            name=name, pool=pool, ping_callable=ping_callable, idle_timeout=idle_timeout
        )
        logger.debug("Pool зарегистрирован в PoolHealthMonitor: %s", name)

    async def start(self) -> None:
        """Запускает background-task monitor-loop (только при flag ON).

        Проверяет feature-flag ``pool_health_monitor`` через lazy-import.
        Если flag OFF — метод завершается немедленно без создания задачи.
        Повторный вызов при уже запущенном monitor'е — no-op.
        """
        if self._running:
            logger.debug("PoolHealthMonitor уже запущен — пропуск start()")
            return

        if not _is_flag_enabled():
            logger.debug(
                "PoolHealthMonitor: feature_flag pool_health_monitor=OFF — "
                "background-task не создаётся"
            )
            return

        self._running = True
        from src.backend.core.utils.task_registry import (
            get_task_registry,  # noqa: PLC0415
        )

        self._task = get_task_registry().create_task(
            self._monitor_loop(), name="pool-health-monitor"
        )
        logger.info(
            "PoolHealthMonitor запущен (tick_interval=%.1fs, pools=%d)",
            self.tick_interval,
            len(self._pools),
        )

    async def stop(self) -> None:
        """Graceful-остановка monitor-loop.

        Отменяет background-task и ожидает его завершения. Безопасно
        вызывать при незапущенном monitor'е (no-op).
        """
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("PoolHealthMonitor остановлен")

    async def tick(self) -> None:
        """Одна итерация health-check для всех зарегистрированных пулов.

        Для каждого пула проверяет, прошло ли больше ``idle_timeout`` секунд
        с момента последнего пинга. Если да — вызывает ``ping_callable``.
        Исключения из ping_callable перехватываются и логируются — они НЕ
        прерывают проверку остальных пулов.
        """
        now = time.monotonic()
        for entry in list(self._pools.values()):
            elapsed = now - entry.last_ping_at
            if elapsed < entry.idle_timeout:
                continue
            await self._ping_pool(entry, now)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Внутренний цикл фоновой задачи.

        Выполняет :meth:`tick` каждые ``tick_interval`` секунд пока
        ``_running`` равен True. При CancelledError завершается gracefully.
        """
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("PoolHealthMonitor tick error: %s", exc)

            try:
                await asyncio.sleep(self.tick_interval)
            except asyncio.CancelledError:
                break

    async def _ping_pool(self, entry: PoolEntry, now: float) -> None:
        """Вызывает ping_callable для одного пула с обработкой ошибок.

        Args:
            entry: Запись зарегистрированного пула.
            now: Текущее время (monotonic) для обновления last_ping_at.
        """
        try:
            await entry.ping_callable()
            entry.last_ping_at = now
            logger.debug(
                "Pool ping OK: %s (elapsed=%.1fs)",
                entry.name,
                now - entry.last_ping_at + (now - entry.last_ping_at),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Pool ping FAIL: %s — %s (пул помечен, idle-timeout сброшен)",
                entry.name,
                exc,
            )
            # Сбрасываем таймер — следующий ping произойдёт через idle_timeout
            entry.last_ping_at = now


# ---------------------------------------------------------------------------
# Feature-flag lazy accessor
# ---------------------------------------------------------------------------


def _is_flag_enabled() -> bool:
    """Проверяет feature-flag ``pool_health_monitor`` через lazy-import.

    Возвращает False при любой ошибке импорта (CI, тесты без DI-init).
    Этот helper изолирует точку принятия решения для unit-тестирования.

    Returns:
        bool: True если флаг включён, иначе False.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.pool_health_monitor
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_monitor_instance: PoolHealthMonitor | None = None


def get_pool_monitor() -> PoolHealthMonitor:
    """Возвращает singleton PoolHealthMonitor.

    Создаёт экземпляр при первом вызове (lazy-init). Singleton НЕ создаёт
    background-task автоматически — для этого нужен явный вызов
    :meth:`PoolHealthMonitor.start` из lifespan при включённом flag.

    Returns:
        PoolHealthMonitor: Единственный экземпляр в рамках процесса.
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PoolHealthMonitor()
    return _monitor_instance
