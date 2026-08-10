"""BPMN Gateway DSL (cycle 33 restore, closes P0 #8 + #9)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from src.backend.dsl.workflow.builder._protocol import _WorkflowBuilderProtocol

if TYPE_CHECKING:
    from src.backend.dsl.workflow.gateways import BranchSpec


class GatewayMixin(_WorkflowBuilderProtocol):
    """BPMN Gateway DSL (XOR/AND/OR) для WorkflowBuilder.

    Cycle 33 restore: методы удалёны в cycle 3 (Layer 6 refactor 53bf6c3c)
    вместе с :class:`~dsl.workflow.gateways.GatewayCompiler`. Восстановлены
    для cycle 33, runtime-компиляция — в
    :mod:`src.backend.dsl.workflow.compiler.gateways`.

    Builder-методы пушат :class:`ActivityDeclaration` с
    ``args["gateway"]`` = :class:`~dsl.workflow.gateways.GatewaySpec`
    instance (или dict в BPMN-формате). Dispatch на
    ``compile_xor/and/or`` — в :func:`compile_activity_step` (cycle 33).
    """

    __slots__ = ()

    def gateway_xor(self, *branches: BranchSpec) -> Self:
        """B-08/B-09 fix (cycle 33): добавить XOR (exclusive) gateway.

        Семантика: из переданных веток выполняется **первая**, чьё
        ``condition`` истинно; ветка с ``condition=None`` — fallback
        (default branch). Если ни одна ветка не matched И нет default —
        gateway возвращает ``None`` без побочных эффектов.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec
        from src.backend.dsl.workflow.spec import ActivityDeclaration

        spec = GatewaySpec(kind="xor", branches=list(branches))
        self._steps.append(
            ActivityDeclaration(
                name=f"__gateway__xor_{len(self._steps)}",
                args={"gateway": spec},
            )
        )
        return self

    def gateway_and(self, *branches: BranchSpec) -> Self:
        """B-08 fix (cycle 33): добавить AND (parallel) gateway — fan-out, join-all.

        Семантика: все ветки запускаются параллельно через
        ``asyncio.gather``; workflow продолжается только после
        завершения **всех** веток (join-all).

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec
        from src.backend.dsl.workflow.spec import ActivityDeclaration

        spec = GatewaySpec(kind="and", branches=list(branches))
        self._steps.append(
            ActivityDeclaration(
                name=f"__gateway__and_{len(self._steps)}",
                args={"gateway": spec},
            )
        )
        return self

    def gateway_or(self, *branches: BranchSpec) -> Self:
        """B-09 fix (cycle 33): добавить OR (inclusive) gateway — race, cancel losers.

        Семантика: все ветки запускаются как ``asyncio.Task``; завершение
        после **первой** завершённой (race), остальные ``task.cancel()``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec
        from src.backend.dsl.workflow.spec import ActivityDeclaration

        spec = GatewaySpec(kind="or", branches=list(branches))
        self._steps.append(
            ActivityDeclaration(
                name=f"__gateway__or_{len(self._steps)}",
                args={"gateway": spec},
            )
        )
        return self
