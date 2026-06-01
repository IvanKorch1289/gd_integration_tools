"""TaskWatchdog — мониторинг deadline'ов зарегистрированных asyncio-задач (V15 R-V15-11).

Назначение:

* Регистрация живых задач с deadline_seconds.
* Периодический background-tick: если elapsed > deadline → warning + cancel.
* Управляется feature-flag ``task_watchdog_deadline`` (default-OFF).
* Singleton доступен через :func:`get_task_watchdog`.

Использование::

    watchdog = get_task_watchdog()
    task = asyncio.create_task(my_coro(), name="heavy-job")
    watchdog.register(task, deadline_seconds=30.0, name="heavy-job")
    await watchdog.start()
    ...
    await watchdog.stop()

Предпочтительный путь — использовать :class:`TaskRegistry` с параметром
``deadline_seconds``, который автоматически оборачивает корутину в Watchdog.
:class:`TaskWatchdog` является дополнительным слоем мониторинга живых задач
без перезапуска/оборачивания.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

__all__ = ("TaskWatchdog", "get_task_watchdog")

_logger = logging.getLogger(__name__)

# Период между итерациями tick() в секундах.
DEFAULT_TICK_INTERVAL: float = 5.0


@dataclass(slots=True)
class _Registration:
    """Запись о зарегистрированной задаче."""

    task: asyncio.Task  # type: ignore[type-arg]
    deadline_seconds: float
    name: str
    registered_at: float = field(default_factory=time.monotonic)


class TaskWatchdog:
    """Мониторинг deadline'ов зарегистрированных asyncio-задач.

    Args:
        tick_interval: Период опроса в секундах (по умолчанию 5.0).
        cancel_on_deadline: Если ``True`` — отменяет задачу при превышении
            deadline. Если ``False`` — только предупреждение в лог.
    """

    def __init__(
        self,
        *,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        cancel_on_deadline: bool = True,
    ) -> None:
        self._tick_interval = tick_interval
        self._cancel_on_deadline = cancel_on_deadline
        self._registrations: list[_Registration] = []
        self._monitor_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stopped: bool = False

    def register(
        self,
        task: asyncio.Task,  # type: ignore[type-arg]
        deadline_seconds: float,
        name: str = "",
    ) -> None:
        """Зарегистрировать задачу с deadline.

        Args:
            task: Объект asyncio.Task для наблюдения.
            deadline_seconds: Максимальное время выполнения в секундах.
            name: Человекочитаемое имя для логов (по умолчанию — пустая строка).
        """
        # Lazy-import feature_flags, чтобы избежать циклических зависимостей
        # при загрузке пакета.
        from src.backend.core.config.features import feature_flags  # noqa: PLC0415

        if not feature_flags.task_watchdog_deadline:
            return

        task_name = name or task.get_name() or "<unnamed>"
        self._registrations.append(
            _Registration(task=task, deadline_seconds=deadline_seconds, name=task_name)
        )

    async def start(self) -> None:
        """Запустить background-монитор tick-loop.

        No-op если feature-flag ``task_watchdog_deadline`` выключен.
        Повторный вызов идемпотентен — второй монитор не запускается.
        """
        from src.backend.core.config.features import feature_flags  # noqa: PLC0415

        if not feature_flags.task_watchdog_deadline:
            return
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        self._stopped = False
        from src.backend.core.utils.task_registry import (
            get_task_registry,  # noqa: PLC0415
        )

        self._monitor_task = get_task_registry().create_task(
            self._monitor_loop(), name="task-watchdog-monitor"
        )

    async def stop(self) -> None:
        """Остановить background-монитор.

        Идемпотентен: безопасно вызывать несколько раз или до start().
        """
        self._stopped = True
        task = self._monitor_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                pass

    async def tick(self) -> None:
        """Одна итерация проверки deadline'ов.

        Для каждой зарегистрированной живой задачи проверяет elapsed.
        Если elapsed > deadline — логирует warning и опционально cancels.
        Завершённые задачи автоматически убираются из списка.
        """
        from src.backend.core.config.features import feature_flags  # noqa: PLC0415

        if not feature_flags.task_watchdog_deadline:
            return

        now = time.monotonic()
        alive: list[_Registration] = []

        for reg in self._registrations:
            if reg.task.done():
                # Задача уже завершилась — не отслеживаем.
                continue
            elapsed = now - reg.registered_at
            if elapsed > reg.deadline_seconds:
                _logger.warning(
                    "task_watchdog.deadline_exceeded",
                    extra={
                        "task_name": reg.name,
                        "deadline_seconds": reg.deadline_seconds,
                        "elapsed_seconds": round(elapsed, 3),
                        "cancel": self._cancel_on_deadline,
                    },
                )
                if self._cancel_on_deadline and not reg.task.done():
                    reg.task.cancel()
                # Не добавляем в alive — мониторинг завершён.
            else:
                alive.append(reg)

        self._registrations = alive

    async def _monitor_loop(self) -> None:
        """Внутренний цикл monitor'а."""
        try:
            while not self._stopped:
                await asyncio.sleep(self._tick_interval)
                try:
                    await self.tick()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "task_watchdog.tick_error", extra={"error": repr(exc)}
                    )
        except asyncio.CancelledError:
            raise


# ─── Singleton ──────────────────────────────────────────────────────────────

_watchdog: TaskWatchdog | None = None


def get_task_watchdog() -> TaskWatchdog:
    """Singleton-аксессор. Создаёт экземпляр при первом обращении.

    Returns:
        Глобальный :class:`TaskWatchdog`.
    """
    global _watchdog  # noqa: PLW0603
    if _watchdog is None:
        _watchdog = TaskWatchdog()
    return _watchdog


def _reset_task_watchdog() -> None:
    """Сбросить singleton (только для unit-тестов)."""
    global _watchdog  # noqa: PLW0603
    _watchdog = None
