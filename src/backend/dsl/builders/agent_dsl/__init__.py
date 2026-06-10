"""Agent DSL package (S51 W3 decomp from agent_dsl.py 771 LOC).

17 methods decomposed в ``orchestration.py`` (8) + ``infra.py`` (9).

Backward-compat: ``from src.backend.dsl.builders.agent_dsl import AgentDSLMixin``
works через re-export ниже.
"""

from __future__ import annotations

from src.backend.dsl.builders.agent_dsl.infra import (
    InfraMixin,  # S51 W3: MRO composition
)
from src.backend.dsl.builders.agent_dsl.orchestration import (
    OrchestrationMixin,  # S51 W3: MRO composition
)


class AgentDSLMixin(OrchestrationMixin, InfraMixin):
    """MRO composition: OrchestrationMixin (8) + InfraMixin (9) = 17 methods."""

    __slots__ = ()


__all__ = ("AgentDSLMixin",)
