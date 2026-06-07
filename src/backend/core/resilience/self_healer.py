"""Self-healer — автоматическое восстановление после ошибок через APScheduler.

Периодически вызывает health-checks компонентов, и при восстановлении —
переводит :class:`DegradationManager` из degraded в normal mode.

Использует ``AsyncIOScheduler`` из APScheduler (уже присутствует в deps),
что даёт persistence задач, надёжный shutdown и совместимость с
corutine-функциями из коробки. Fallback на простой ``asyncio.sleep``-loop
сохранён для минимального окружения без APScheduler.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

from collections.abc import Callable
from typing import Any

from src.backend.core.resilience.degradation import degradation_manager
from src.backend.core.utils.task_registry import get_task_registry

__all__ = ("SelfHealer", "get_self_healer")

logger = get_logger(__name__)


class SelfHealer:
    """Self-healing цикл: периодически проверяет упавшие компоненты."""

    def __init__(self, check_interval: int = 30) -> None:
        self._interval = check_interval
        self._task: asyncio.Task | None = None
        self._scheduler: Any = None
        self._running = False
        self._healers: dict[str, Callable[[], Any]] = {}

    def register_healer(self, component: str, health_check: Callable[[], Any]) -> None:
        self._healers[component] = health_check

    async def start(self) -> None:
        self._running = True
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self._scheduler = AsyncIOScheduler()
            self._scheduler.add_job(
                self._run_healers, "interval", seconds=self._interval, id="self_healer"
            )
            self._scheduler.start()
            logger.info(
                "SelfHealer started via APScheduler (interval=%ds)", self._interval
            )
            return
        except Exception as exc:
            logger.debug("APScheduler недоступен, fallback на asyncio: %s", exc)

        self._task = get_task_registry().create_task(
            self._heal_loop(), name="self-healer-loop"
        )
        logger.info(
            "SelfHealer started via asyncio loop (interval=%ds)", self._interval
        )

    async def stop(self) -> None:
        self._running = False
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        if self._task:
            self._task.cancel()

    async def _run_healers(self) -> None:
        """Один раунд проверок — используется APScheduler'ом."""
        for name, check in self._healers.items():
            if degradation_manager.is_available(name):
                continue
            try:
                result = check()
                if hasattr(result, "__await__"):
                    result = await result
                if result:
                    degradation_manager.report_success(name)
                    logger.info("SelfHealer: %s восстановлен", name)
            except Exception as exc:
                logger.debug("SelfHealer: %s ещё down: %s", name, exc)

    async def _heal_loop(self) -> None:
        """Fallback-цикл без APScheduler."""
        while self._running:
            await asyncio.sleep(self._interval)
            await self._run_healers()


_self_healer: SelfHealer | None = None


def get_self_healer() -> SelfHealer:
    """Singleton-аксессор для глобального SelfHealer."""
    global _self_healer
    if _self_healer is None:
        _self_healer = SelfHealer()
    return _self_healer
