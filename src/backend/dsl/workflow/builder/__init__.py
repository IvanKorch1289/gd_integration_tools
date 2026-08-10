"""WorkflowBuilder package (S58 W4 decomp from builder.py 554 LOC).

21 methods decomposed в 6 mixin files (cycle 33 restore):
- ``sla_mixin.py`` (2): sla, activity
- ``workflow_mixin.py`` (2): saga, build
- ``wait_mixin.py`` (3): wait_for_signal, sleep, sensor
- ``gateway_mixin.py`` (3): gateway_xor, gateway_and, gateway_or  [cycle 33 restore]
- ``ai_mixin.py`` (1): invoke_agent (BIG 66 LOC)
- ``lifecycle_mixin.py`` (6): reflect, checkpoint, guardrail, pause, resume, escalate

Cycle 3 → Cycle 33: gateway_mixin был удалён (Layer 6 refactor 53bf6c3c,
XOR/AND/OR — silent no-op → fail-fast в compile). Cycle 33 восстанавливает
mixin + runtime-компиляцию (compiler/gateways.py) для closes P0 #8 + #9.

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
from src.backend.dsl.workflow.builder.gateway_mixin import (
    GatewayMixin,  # cycle 33 restore: BPMN gateway DSL (P0 #8 + #9)
)
from src.backend.dsl.workflow.builder.lifecycle_mixin import (
    LifecycleMixin,  # S58 W4: MRO
)
from src.backend.dsl.workflow.builder.sla_mixin import SlaMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.wait_mixin import WaitMixin  # S58 W4: MRO
from src.backend.dsl.workflow.builder.workflow_mixin import WorkflowMixin  # S58 W4: MRO

__all__ = ("WorkflowBuilder", "SagaBuilder")


class WorkflowBuilder(
    SlaMixin,
    WorkflowMixin,
    WaitMixin,
    AiAgentMixin,
    LifecycleMixin,
    GatewayMixin,  # cycle 33 restore: 17 methods = 14 + 3 gateway
):
    """Workflow DSL builder (6 mixins = 17 methods + 4 core).

    Cycle 33: GatewayMixin восстановлен (3 метода: gateway_xor/and/or).
    Runtime-компиляция — в :mod:`src.backend.dsl.workflow.compiler.gateways`.
    MRO: Sla → Workflow → Wait → Ai → Lifecycle → Gateway.
    """

    __slots__ = (
        "_name",
        "_description",
        "_version",
        "_steps",
        "_default_timeout_s",
        "_default_retry_policy",
        "_sla",
    )

    def __init__(self, name: str, *, description: str | None = None) -> None:
        self._name = name
        self._description = description
        self._version: str = "1.0"
        self._steps: list[WorkflowStep] = []
        self._default_timeout_s: float = 300.0
        self._default_retry_policy: RetryPolicy | None = None
        self._sla: Any | None = None

    def description(self, text: str) -> Self:
        """Установить человекочитаемое описание workflow."""
        self._description = text
        return self

    def then(self, step: WorkflowStep) -> Self:
        """D-AUDIT-A8-06 fix (cycle 1): добавить произвольный WorkflowStep в pipeline.

        Fluent alias для добавления шага декларативно. Используется в
        extensions/core_entities/orders/workflows/orders_dsl.py и других
        DSL builders, где удобнее выразить шаги через
        ``.then(ActivityDeclaration(...)).then(SensorDeclaration(...))``
        вместо последовательных вызовов ``.activity(...).sensor(...)``.

        Args:
            step: WorkflowStep (ActivityDeclaration | SagaDeclaration |
                SignalWaitDeclaration | SleepDeclaration | PauseDeclaration |
                ResumeDeclaration | SensorDeclaration | AgentInvokeDeclaration |
                ReflectDeclaration | CheckpointDeclaration | GuardrailDeclaration |
                EscalateDeclaration).

        Returns:
            Self для fluent chaining.
        """
        self._steps.append(step)
        return self

    def version(self, ver: str) -> Self:
        """Установить semver-версию workflow (например, ``"2.1"``).

        Cycle 27 W3: builder now пробрасывает user-supplied version в
        ``WorkflowDeclaration.version`` через ``build()``. Без этого
        вызова версия всегда была default ``"1.0"``.
        """
        self._version = ver
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
