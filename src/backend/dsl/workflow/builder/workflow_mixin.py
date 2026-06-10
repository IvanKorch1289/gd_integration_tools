from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any, Self

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    MemoryScope,
    PauseDeclaration,
    ResumeDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
)

if TYPE_CHECKING:
    from src.backend.dsl.workflow.gateways import BranchSpec

class WorkflowMixin:
    """saga + final build для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

    def saga(self) -> SagaBuilder:
        """Открыть саб-builder для saga-шага.

        Завершить вложенный chain нужно через :meth:`SagaBuilder.end_saga`,
        чтобы вернуть управление родительскому ``WorkflowBuilder``.
        """
        return SagaBuilder(self)

    def build(self) -> WorkflowDeclaration:
        """Собрать и провалидировать :class:`WorkflowDeclaration`.

        Pydantic-валидация выполняется здесь: пустой ``steps``, дубликаты
        и прочие нарушения превращаются в ``pydantic.ValidationError``.
        """
        return WorkflowDeclaration(
            name=self._name,
            description=self._description,
            steps=self._steps,
            default_timeout_s=self._default_timeout_s,
            default_retry_policy=self._default_retry_policy,
            sla=self._sla,
        )

