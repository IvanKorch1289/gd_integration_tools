"""R2.2 — `RetryWithCompensation` primitive.

Retry workflow-step с exponential backoff'ом + compensate при
исчерпании попыток. Отличается от tenacity-retry тем, что:
* state retry-counter durable (выживает рестарт),
* при провале — выполняет compensate (который сам tenacity не делает).

Используется в кросс-сервисных интеграциях, где временный failure
(network blip) ожидаемый, но quota-exhausted compensation
(возврат денег / отмена брони) нужно сделать корректно.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("RetryPolicy", "RetryWithCompensation")


ActivityFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class RetryPolicy(BaseModel):
    """Политика retry: exponential backoff + max attempts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    initial_delay_s: float = Field(default=1.0, ge=0)
    multiplier: float = Field(default=2.0, ge=1)
    max_delay_s: float = Field(default=60.0, ge=0)
    retryable_exceptions: tuple[str, ...] = ()
    """Имена exception-классов, на которых retry применим. Пустой
    кортеж — retry на любых ``Exception`` (default)."""


@runtime_checkable
class RetryWithCompensation(Protocol):
    """Контракт retry-with-compensation primitive."""

    async def run(
        self,
        *,
        operation_id: str,
        forward: ActivityFn,
        compensate: ActivityFn | None,
        input: dict[str, Any],
        policy: RetryPolicy,
        namespace: str = "default",
    ) -> dict[str, Any]:
        """Выполнить ``forward`` с retry; при исчерпании — ``compensate``.

        :returns: результат успешного forward.
        :raises: исключение последнего failed forward, если compensate
            не задан или сам бросил.
        """
        ...
