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

class GatewayMixin:
    """gateway_xor + gateway_and + gateway_or для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

    def gateway_xor(self, *branches: BranchSpec) -> Self:
        """Добавить XOR (exclusive) gateway — выбирает первую активную ветку.

        Семантика: из переданных веток выполняется **первая**, чьё
        ``condition`` истинно; ветка с ``condition=None`` — fallback.
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="xor", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

    def gateway_and(self, *branches: BranchSpec) -> Self:
        """Добавить AND (parallel) gateway — параллельный fan-out, ждёт всех.

        Семантика: все ветки запускаются одновременно; workflow
        продолжается только после завершения **всех** веток (join-all).
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="and", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

    def gateway_or(self, *branches: BranchSpec) -> Self:
        """Добавить OR (inclusive) gateway — ждёт первую активную ветку.

        Семантика: из всех веток с истинным ``condition`` активируются все;
        workflow продолжается после завершения **первой** (wait_any),
        остальные отменяются.
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="or", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

