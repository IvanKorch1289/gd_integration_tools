"""Resilience patterns — graceful degradation, retry budget, bulkhead, self-healing.

Основные идеи:
- При падении Redis/DB приложение продолжает работать с деградацией
- RetryBudget защищает от retry storm
- Bulkhead изолирует ресурсы между сервисами
- Self-healing: автоматическое восстановление после ошибок
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

__all__ = (
    "DegradationMode",
    "DegradationManager",
    "degradation_manager",
    "RetryBudget",
    "Bulkhead",
    "SelfHealer",
)

logger = logging.getLogger(__name__)


# ─────────── Graceful Degradation ───────────


class DegradationMode(Enum):
    FULL = "full"  # Всё работает
    DEGRADED = "degraded"  # Часть функций отключена
    EMERGENCY = "emergency"  # Только критичные функции


@dataclass(slots=True)
class ComponentState:
    name: str
    available: bool = True
    last_check: float = 0.0
    failure_count: int = 0
    fallback_active: bool = False


class DegradationManager:
    """Управляет graceful degradation при недоступности компонентов.

    При падении Redis:
    - Fallback на in-memory cache
    - Rate limiting отключается (fail-open)
    - Sessions храним в памяти
    """

    def __init__(self) -> None:
        self._components: dict[str, ComponentState] = {}
        self._fallbacks: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fallback: Callable[..., Any] | None = None) -> None:
        self._components[name] = ComponentState(name=name)
        if fallback:
            self._fallbacks[name] = fallback

    def report_failure(self, name: str) -> None:
        if name not in self._components:
            self.register(name)
        state = self._components[name]
        state.failure_count += 1
        state.last_check = time.monotonic()
        if state.failure_count >= 3 and state.available:
            state.available = False
            state.fallback_active = True
            logger.warning("Component '%s' degraded — activating fallback", name)

    def report_success(self, name: str) -> None:
        if name not in self._components:
            self.register(name)
        state = self._components[name]
        if not state.available:
            logger.info("Component '%s' recovered", name)
        state.available = True
        state.failure_count = 0
        state.fallback_active = False

    def get_fallback(self, name: str) -> Callable[..., Any] | None:
        return (
            self._fallbacks.get(name)
            if name in self._components and self._components[name].fallback_active
            else None
        )

    def is_available(self, name: str) -> bool:
        return self._components.get(name, ComponentState(name=name)).available

    def mode(self) -> DegradationMode:
        critical = ["database", "redis"]
        critical_down = sum(
            1
            for n in critical
            if n in self._components and not self._components[n].available
        )
        if critical_down >= 2:
            return DegradationMode.EMERGENCY
        if critical_down >= 1 or any(
            not s.available for s in self._components.values()
        ):
            return DegradationMode.DEGRADED
        return DegradationMode.FULL

    def report(self) -> dict[str, Any]:
        return {
            "mode": self.mode().value,
            "components": {
                name: {
                    "available": state.available,
                    "failures": state.failure_count,
                    "fallback_active": state.fallback_active,
                }
                for name, state in self._components.items()
            },
        }


degradation_manager = DegradationManager()


# ─────────── Retry Budget ───────────


class RetryBudget:
    """Глобальный бюджет ретраев — защита от retry storm.

    Идея: не более ``max_ratio`` (по умолчанию 20%) запросов в окне могут
    быть retries. При превышении — быстрые fail.

    Реализация использует :mod:`collections.deque` с фиксированной ёмкостью
    для эффективного скользящего окна (O(1) добавление, без list-comprehension
    на каждом вызове). Для настоящих ретраев вокруг HTTP-клиента рекомендуется
    использовать ``tenacity.AsyncRetrying`` поверх этого бюджета.
    """

    def __init__(self, window_seconds: int = 60, max_ratio: float = 0.2) -> None:
        from collections import deque

        self._window = window_seconds
        self._max_ratio = max_ratio
        # maxlen не подходит — окно по времени, а не по числу событий.
        self._total: deque[float] = deque()
        self._retries: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def record_request(self) -> None:
        async with self._lock:
            self._total.append(time.monotonic())
            self._trim()

    async def try_retry(self) -> bool:
        """Возвращает True если retry разрешён."""
        async with self._lock:
            self._trim()
            total = len(self._total)
            retries = len(self._retries)
            if total == 0:
                return True
            ratio = retries / total
            if ratio >= self._max_ratio:
                return False
            self._retries.append(time.monotonic())
            return True

    def _trim(self) -> None:
        """Удаляет события вне окна из deque (O(1) на элемент c левого края)."""
        cutoff = time.monotonic() - self._window
        while self._total and self._total[0] < cutoff:
            self._total.popleft()
        while self._retries and self._retries[0] < cutoff:
            self._retries.popleft()

    def stats(self) -> dict[str, Any]:
        return {
            "total_in_window": len(self._total),
            "retries_in_window": len(self._retries),
            "ratio": len(self._retries) / max(len(self._total), 1),
            "max_ratio": self._max_ratio,
        }


# ─────────── Bulkhead Isolation ───────────


class Bulkhead:
    """Bulkhead pattern — изоляция ресурсов по semaphore.

    Максимум N параллельных вызовов per service — падение одного
    не съедает все воркеры для других.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def register(self, service: str, max_concurrent: int = 10) -> None:
        self._semaphores[service] = asyncio.Semaphore(max_concurrent)

    async def acquire(self, service: str, timeout: float = 30.0) -> bool:
        """Захватывает слот. Возвращает False при таймауте."""
        if service not in self._semaphores:
            self.register(service)
        sem = self._semaphores[service]
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def release(self, service: str) -> None:
        if service in self._semaphores:
            self._semaphores[service].release()

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            name: {"available": sem._value, "locked": sem.locked()}
            for name, sem in self._semaphores.items()
        }


# ─────────── Self-Healer ───────────


class SelfHealer:
    """Автоматическое восстановление после ошибок через APScheduler.

    Периодически вызывает health-checks компонентов, и при восстановлении —
    переводит :class:`DegradationManager` из degraded в normal mode.

    Использует ``AsyncIOScheduler`` из APScheduler (уже присутствует в deps),
    что даёт persistence задач, надёжный shutdown и совместимость с
    corutine-функциями из коробки. Fallback на простой ``asyncio.sleep``-loop
    сохранён для минимального окружения без APScheduler.
    """

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
        # Попытка через APScheduler (основной путь).
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
        except Exception as exc:  # noqa: BLE001
            logger.debug("APScheduler недоступен, fallback на asyncio: %s", exc)

        self._task = asyncio.create_task(self._heal_loop())
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
            except Exception as exc:  # noqa: BLE001
                logger.debug("SelfHealer: %s ещё down: %s", name, exc)

    async def _heal_loop(self) -> None:
        """Fallback-цикл без APScheduler."""
        while self._running:
            await asyncio.sleep(self._interval)
            await self._run_healers()


_retry_budget: RetryBudget | None = None
_bulkhead: Bulkhead | None = None
_self_healer: SelfHealer | None = None


def get_retry_budget() -> RetryBudget:
    global _retry_budget
    if _retry_budget is None:
        _retry_budget = RetryBudget()
    return _retry_budget


def get_bulkhead() -> Bulkhead:
    global _bulkhead
    if _bulkhead is None:
        _bulkhead = Bulkhead()
    return _bulkhead


def get_self_healer() -> SelfHealer:
    global _self_healer
    if _self_healer is None:
        _self_healer = SelfHealer()
    return _self_healer
