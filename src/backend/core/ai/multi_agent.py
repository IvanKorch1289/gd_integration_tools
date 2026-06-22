"""Capability-checked facade для multi-agent supervisor (S124 W1).

ADR-0207: extensions/credit_pipeline/agents/__init__.py импортирует
``MultiAgentSupervisor`` и ``AgentSpec`` из ``services.ai.multi_agent``
(это package, supervisor.py).
"""

from __future__ import annotations
from src.backend.core.logging import get_logger


from src.backend.services.ai.multi_agent.supervisor import (  # noqa: F401
    AgentSpec,
    MultiAgentSupervisor,
    MultiAgentSupervisorUnavailable,
)

logger = get_logger(__name__)


__all__ = ("AgentSpec", "MultiAgentSupervisor", "MultiAgentSupervisorUnavailable")
