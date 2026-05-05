"""R2.2 — `DeadlineWithEscalation` primitive.

Запускает workflow-операцию с deadline; при превышении — эскалирует
по цепочке (sentry alert → ops on-call → manual override).
Реализация — Temporal `start_workflow(execution_timeout=...)` +
escalation chain через signals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

__all__ = ("DeadlinePolicy", "DeadlineWithEscalation")


EscalationFn = Callable[[dict[str, Any]], Awaitable[None]]
"""Сигнатура escalation-handler'а: принимает context (operation_id,
elapsed, остаток payload), возвращает None."""


class DeadlinePolicy(BaseModel):
    """Политика deadline + escalation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deadline: timedelta
    escalation_after: timedelta | None = None
    """Если задан — escalate'ить через ``deadline - escalation_after``
    до hard-deadline (например, escalate за 5 мин до deadline)."""
    cancel_on_deadline: bool = True
    """Если ``True`` — после hard-deadline отменить workflow; иначе
    оставить running и положиться на escalation."""


@runtime_checkable
class DeadlineWithEscalation(Protocol):
    """Контракт deadline-with-escalation primitive."""

    async def run(
        self,
        *,
        operation_id: str,
        forward: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        escalate: EscalationFn,
        input: dict[str, Any],
        policy: DeadlinePolicy,
        namespace: str = "default",
    ) -> dict[str, Any]:
        """Выполнить ``forward`` с deadline; ``escalate`` вызывается
        при приближении к deadline (если ``escalation_after`` задан).

        :returns: результат forward, если уложился в deadline.
        :raises TimeoutError: если ``cancel_on_deadline=True`` и forward
            не уложился.
        """
        ...
