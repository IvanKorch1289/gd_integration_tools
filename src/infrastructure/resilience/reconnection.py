"""Reconnection strategies (MuleSoft-style) для infrastructure-клиентов.

IL2.3 (ADR-022): три стратегии переподключения, которые оборачивают попытку
установить соединение (`dial`) в tenacity-политику. Используются в
`InfrastructureClient.start()` и при reload.

Паттерн эквивалентен MuleSoft `<reconnection><reconnect-forever/></reconnection>`
и Camel `RouteBuilder.errorHandler(defaultErrorHandler().maximumRedeliveries(...))`.

Стратегии:

* `ReconnectForever(delay, max_delay, multiplier)` — пытаемся вечно, exponential
  backoff с крышей `max_delay`. Подходит Kafka consumer / Rabbit consumer /
  IMAP monitor — долгоживущие потоки, где ручной intervene неприемлем.

* `ReconnectN(attempts, delay, multiplier)` — ограниченное число попыток, потом
  `ReconnectionError`. Подходит cold-start HTTP / gRPC клиентов — если upstream
  недоступен минуту, лучше fail-fast в startup.

* `NoReconnect()` — просто один вызов `dial()`, никаких retry. Подходит для
  unit-test / dry-run режимов + как explicit opt-out.

Стратегия выбирается per-client из настройки `settings.<client>.reconnection`
(строка) или инжектится напрямую. Каждая успешная попытка сбрасывает счётчик
— это отличает reconnection от retry-бюджета (`retry_budget.py`).

Метрики: каждая попытка (success/failure) инкрементит Counter
`infra_client_reconnect_attempts_total{client,outcome}`.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final, TypeVar

from prometheus_client import Counter


_logger = logging.getLogger(__name__)

T = TypeVar("T")

ReconnectOutcome = Any  # Literal["success", "failure", "giveup"] — см. ниже.


reconnect_attempts_total: Final = Counter(
    "infra_client_reconnect_attempts_total",
    "Total reconnection attempts per client (IL2.3).",
    labelnames=("client", "outcome"),
)


class ReconnectionError(RuntimeError):
    """Бросается, когда `ReconnectN` исчерпал попытки."""


class ReconnectionStrategy(ABC):
    """Интерфейс стратегии переподключения.

    Реализация получает `client_name` (для метрик) и callable `dial`,
    возвращает то, что вернул `dial`. При провале всех попыток — бросает
    `ReconnectionError` (либо оригинальное исключение).
    """

    @abstractmethod
    async def run(self, client_name: str, dial: Callable[[], Awaitable[T]]) -> T:
        """Выполнить попытку соединения с учётом стратегии."""


@dataclass(slots=True)
class ReconnectForever(ReconnectionStrategy):
    """Бесконечное переподключение с exponential backoff.

    * `initial_delay` — базовая задержка между попытками (сек).
    * `max_delay` — крышка. После этой точки задержка не растёт.
    * `multiplier` — коэффициент экспоненты (>1.0).

    Алгоритм: `delay_n = min(max_delay, initial_delay * multiplier ** n)`.

    Безопасно вызывать в tight-loop сценариях — cooperative cancel через
    `asyncio.sleep` гарантирует, что shutdown не блокируется.
    """

    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0

    async def run(self, client_name: str, dial: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        delay = self.initial_delay
        while True:
            attempt += 1
            try:
                result = await dial()
                reconnect_attempts_total.labels(client=client_name, outcome="success").inc()
                if attempt > 1:
                    _logger.info(
                        "reconnect succeeded",
                        extra={"client": client_name, "attempt": attempt},
                    )
                return result
            except Exception as exc:  # noqa: BLE001
                reconnect_attempts_total.labels(client=client_name, outcome="failure").inc()
                _logger.warning(
                    "reconnect failed; retrying",
                    extra={
                        "client": client_name,
                        "attempt": attempt,
                        "delay_s": delay,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                await asyncio.sleep(delay)
                delay = min(self.max_delay, delay * self.multiplier)


@dataclass(slots=True)
class ReconnectN(ReconnectionStrategy):
    """Ограниченное число попыток переподключения.

    После исчерпания — бросает `ReconnectionError` с последней exception-
    цепочкой. Подходит для cold-start-сценариев (startup FastAPI).
    """

    attempts: int = 3
    initial_delay: float = 1.0
    multiplier: float = 2.0

    async def run(self, client_name: str, dial: Callable[[], Awaitable[T]]) -> T:
        delay = self.initial_delay
        last_exc: BaseException | None = None
        for i in range(1, self.attempts + 1):
            try:
                result = await dial()
                reconnect_attempts_total.labels(client=client_name, outcome="success").inc()
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                reconnect_attempts_total.labels(client=client_name, outcome="failure").inc()
                if i == self.attempts:
                    reconnect_attempts_total.labels(client=client_name, outcome="giveup").inc()
                    _logger.error(
                        "reconnect giving up",
                        extra={
                            "client": client_name,
                            "attempts": self.attempts,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    break
                _logger.warning(
                    "reconnect failed",
                    extra={
                        "client": client_name,
                        "attempt": i,
                        "delay_s": delay,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                await asyncio.sleep(delay)
                delay *= self.multiplier
        raise ReconnectionError(
            f"Failed to connect '{client_name}' after {self.attempts} attempts"
        ) from last_exc


@dataclass(slots=True)
class NoReconnect(ReconnectionStrategy):
    """Одна попытка без retry. Любая ошибка пробрасывается."""

    async def run(self, client_name: str, dial: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await dial()
            reconnect_attempts_total.labels(client=client_name, outcome="success").inc()
            return result
        except Exception:
            reconnect_attempts_total.labels(client=client_name, outcome="failure").inc()
            raise


def build(
    policy: str, *, initial_delay: float = 1.0, max_delay: float = 60.0, attempts: int = 3
) -> ReconnectionStrategy:
    """Factory по имени из Settings: ``forever | n_attempts | none``.

    Неизвестное имя → `ValueError`.
    """
    lower = policy.lower().strip()
    if lower in ("forever", "reconnect-forever"):
        return ReconnectForever(initial_delay=initial_delay, max_delay=max_delay)
    if lower in ("n_attempts", "n-attempts", "n"):
        return ReconnectN(attempts=attempts, initial_delay=initial_delay)
    if lower in ("none", "no", "off"):
        return NoReconnect()
    raise ValueError(
        f"Unknown reconnection policy '{policy}'. "
        "Available: forever | n_attempts | none."
    )


__all__ = (
    "ReconnectionStrategy",
    "ReconnectForever",
    "ReconnectN",
    "NoReconnect",
    "ReconnectionError",
    "reconnect_attempts_total",
    "build",
)
