"""WorkflowBuilder package (S58 W4 decomp from builder.py 554 LOC).

21 methods decomposed в 6 mixin files:
- ``sla_mixin.py`` (2): sla, activity
- ``workflow_mixin.py`` (2): saga, build
- ``wait_mixin.py`` (3): wait_for_signal, sleep, sensor
- ``gateway_mixin.py`` (3): gateway_xor, gateway_and, gateway_or
- ``ai_mixin.py`` (1): invoke_agent (BIG 66 LOC)
- ``lifecycle_mixin.py`` (6): reflect, checkpoint, guardrail, pause, resume, escalate

Core (4) остается в __init__.py: __init__, description, default_timeout, default_retry.
SagaBuilder (4 methods) preserved as separate class.

Backward-compat: ``from src.backend.dsl.workflow.builder import WorkflowBuilder`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Self

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    RetryPolicy,
    SagaDeclaration,
    WorkflowStep,
)

if TYPE_CHECKING:
    pass

from src.backend.dsl.workflow.builder.ai_mixin import AiAgentMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.gateway_mixin import GatewayMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.lifecycle_mixin import (
    LifecycleMixin,  # S58 W4: MRO
)
from src.backend.dsl.workflow.builder.sla_mixin import SlaMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.wait_mixin import WaitMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.workflow_mixin import WorkflowMixin  # S58 W4: MRO

__all__ = ("WorkflowBuilder", "SagaBuilder")


class WorkflowBuilder(
    SlaMixin, WorkflowMixin, WaitMixin, GatewayMixin, AiAgentMixin, LifecycleMixin
):
    """Workflow DSL builder (6 mixins = 17 methods + 4 core)."""

    __slots__ = (
        "_name",
        "_description",
        "_steps",
        "_default_timeout_s",
        "_default_retry_policy",
        "_sla",
    )

    def __init__(self, name: str, *, description: str | None = None) -> None:
        self._name = name
        self._description = description
        self._steps: list[WorkflowStep] = []
        self._default_timeout_s: float = 300.0
        self._default_retry_policy: RetryPolicy | None = None
        self._sla: Any | None = None

    def description(self, text: str) -> Self:
        """Установить человекочитаемое описание workflow."""
        self._description = text
        return self

    def default_timeout(self, seconds: float) -> Self:
        """Установить default-timeout для activity без explicit ``timeout_s``."""
        self._default_timeout_s = seconds
        return self

    def default_retry(self, policy: RetryPolicy) -> Self:
        """Установить default retry-политику workflow."""
        self._default_retry_policy = policy
        return self


class SagaBuilder:
    """Саб-builder saga-шага. Аккумулирует forward/compensate цепочки.

    Возврат к родителю — через :meth:`end_saga`. Без вызова ``end_saga``
    saga-шаг НЕ попадает в результирующий workflow.
    """

    def __init__(self, parent: WorkflowBuilder) -> None:
        self._parent = parent
        self._forward: list[ActivityDeclaration] = []
        self._compensate: list[ActivityDeclaration] = []

    def forward(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить forward-activity в saga-цепочку."""
        self._forward.append(
            ActivityDeclaration(
                name=name,
                args=args or {},
                timeout_s=timeout_s,
                retry_policy=retry_policy,
                output_key=output_key,
            )
        )
        return self

    def compensate(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> Self:
        """Добавить compensate-activity (откат forward-шагов)."""
        self._compensate.append(
            ActivityDeclaration(
                name=name,
                args=args or {},
                timeout_s=timeout_s,
                retry_policy=retry_policy,
            )
        )
        return self

    def end_saga(self) -> WorkflowBuilder:
        """Завершить саб-chain и вернуть родительский ``WorkflowBuilder``.

        Pydantic-валидация форвард-цепочки делегируется
        :class:`SagaDeclaration` (минимум 1 forward-шаг обязателен).
        """
        self._parent._steps.append(
            SagaDeclaration(forward=self._forward, compensate=self._compensate)
        )
        return self._parent
