"""R2.2 — Saga primitive поверх `WorkflowBackend`.

Saga = list of (forward, compensate) шагов. При провале шага N —
выполняются compensate шагов N-1, N-2, ..., 0 в обратном порядке.

В отличие от существующего DSL `SagaStep`/`SagaProcessor` (in-process),
этот primitive — **workflow-orchestrated**: каждый forward/compensate
— Temporal Activity (durable, retry'емая, replay-safe). Использовать
для долгих кросс-сервисных транзакций (часы/дни), где in-process saga
теряет state при рестарте.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("SagaPrimitive", "SagaResult", "SagaStep")


ActivityFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Сигнатура forward/compensate: принимает payload, возвращает result."""


class SagaStep(BaseModel):
    """Один шаг saga: forward + опц. compensate.

    `name` — стабильный идентификатор для replay/audit.
    `idempotency_key_path` — path в payload для dedup (Temporal
    activity-level idempotency).
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    forward: ActivityFn
    compensate: ActivityFn | None = None
    max_attempts: int = 3
    idempotency_key_path: str | None = None


class SagaResult(BaseModel):
    """Результат выполнения saga."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool
    completed_steps: tuple[str, ...] = ()
    compensated_steps: tuple[str, ...] = ()
    failure: dict[str, Any] | None = None
    output: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SagaPrimitive(Protocol):
    """Контракт saga-orchestrator'а ядра."""

    async def run(
        self,
        *,
        saga_id: str,
        steps: list[SagaStep],
        input: dict[str, Any],
        namespace: str = "default",
    ) -> SagaResult:
        """Выполнить saga-шаги; при failure — компенсировать в reverse-порядке.

        :param saga_id: уникальный ID для replay/dedup.
        :param steps: упорядоченный список шагов.
        :param input: начальный payload (передаётся в первый ``forward``;
            результат каждого forward становится payload'ом для следующего).
        :param namespace: tenant_id (multi-tenant изоляция в backend'е).
        """
        ...
