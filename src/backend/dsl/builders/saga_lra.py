"""Saga LRA builder mixin for RouteBuilder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.dsl.engine.processors.control_flow import SagaStep
from src.backend.dsl.engine.processors.saga_lra import SagaLRAProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("SagaLRAMixin",)


class SagaLRAMixin:
    """Поведенческий миксин Saga LRA для ``RouteBuilder``.

    Stateless: использует ``self._add`` через MRO; собственных полей
    не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def saga_lra(
        self,
        steps: list[SagaStep],
        *,
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> RouteBuilder:
        """Saga LRA: долгоживущая сага с persistent checkpoints.

        Args:
            steps: Список :class:`SagaStep` (forward + compensate).
            workflow_id: Опц. UUID workflow instance.
            run_id: Опц. execution run id.

        Returns:
            ``RouteBuilder`` для fluent-chain вызовов.
        """
        return self._add(  # type: ignore[attr-defined]
            SagaLRAProcessor(steps=steps, workflow_id=workflow_id, run_id=run_id)
        )
