"""MemoryScope Pydantic model (S28 W2).

Pydantic-версия для YAML workflow declaration.
Runtime dataclass-версия — :class:`core.ai.agent_spec.MemoryScope`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MemoryScope(BaseModel):
    """Memory scope policy для :class:`AgentInvokeDeclaration` (S28 W2).

    Pydantic-версия :class:`core.ai.agent_spec.MemoryScope` для
    декларативного использования в YAML workflow definition.

    Attributes:
        read: Кортеж имён memory resources для чтения.
        write: Кортеж имён memory resources для записи.
        mode: Стратегия изоляции:

            * ``"none"`` — доступ закрыт (no memory access);
            * ``"scoped"`` — isolated namespace per workflow/session;
            * ``"inherited"`` — наследует memory scope вызывающего;
            * ``"shared"`` — shared между всеми агентами workflow.
        write_strategy: Стратегия записи в long-term memory:

            * ``"hot_path"`` — писать сразу после каждого turn;
            * ``"background"`` — batch consolidation в фоне;
            * ``"manual"`` — только явный ``reflect`` step.
    """

    model_config = ConfigDict(extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    mode: Literal["none", "scoped", "inherited", "shared"] = "scoped"
    write_strategy: Literal["hot_path", "background", "manual"] = "background"