"""Capability-checked facade для multi-agent supervisor (S124 W1).

ADR-0207: extensions/credit_pipeline/agents/__init__.py импортирует
``MultiAgentSupervisor`` и ``AgentSpec`` из ``services.ai.multi_agent``
(это package, supervisor.py).
"""

from __future__ import annotations

from src.backend.services.ai.multi_agent.supervisor import (  # noqa: F401
    AgentSpec,
    MultiAgentSupervisor,
    MultiAgentSupervisorUnavailable,
)

__all__ = ("AgentSpec", "MultiAgentSupervisor", "MultiAgentSupervisorUnavailable")
