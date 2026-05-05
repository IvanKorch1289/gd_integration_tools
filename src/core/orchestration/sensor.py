"""R2.2 — `Sensor` primitive.

Long-running watcher, ждущий внешнего условия (file appears, event
in queue, DB-row exists, HTTP status==200). При срабатывании запускает
target action / workflow.

Реализация — Temporal workflow, polling условия через activity'и
с экспоненциальным backoff'ом до match или deadline.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("Sensor", "SensorTrigger")


CheckFn = Callable[[dict[str, Any]], Awaitable[bool]]
"""Сигнатура check-функции sensor'а: возвращает True при match."""


class SensorTrigger(BaseModel):
    """Конфигурация sensor'а."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    sensor_id: str = Field(min_length=1)
    check: CheckFn
    """Активити, проверяющая внешнее условие."""
    poll_interval_s: float = Field(default=5.0, ge=0.1)
    timeout: timedelta | None = None
    """Hard-deadline; ``None`` = wait infinitely."""
    on_match_action: str | None = None
    """Если задан — после match диспетчерится action с тем же payload."""


@runtime_checkable
class Sensor(Protocol):
    """Контракт sensor primitive."""

    async def watch(
        self,
        *,
        trigger: SensorTrigger,
        input: dict[str, Any],
        namespace: str = "default",
    ) -> dict[str, Any]:
        """Запустить watcher; вернуть payload в момент match'а.

        :raises TimeoutError: если ``trigger.timeout`` истёк без match'а.
        """
        ...
