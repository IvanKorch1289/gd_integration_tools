"""Tool Policy Engine — capability-based gating для agent tools (Wave 3 #18)."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "ToolCapability",
    "ToolPolicy",
    "ToolPolicyEngine",
    "get_tool_policy_engine",
)


class ToolCapability(str, enum.Enum):
    """Capability классификация tools."""

    READ = "read"  # safe reads
    WRITE = "write"  # side-effect внутри tenant
    EXTERNAL = "external"  # external API call
    ADMIN = "admin"  # admin operations
    SANDBOX = "sandbox"  # sandboxed code execution


@dataclass(slots=True)
class ToolPolicy:
    """Policy для одного (agent, tool) или (tenant, tool)."""

    tool_name: str
    capability: ToolCapability
    allowed_agents: list[str] = field(default_factory=list)  # empty = all
    allowed_tenants: list[str] = field(default_factory=list)  # empty = all
    requires_approval: bool = False
    max_calls_per_minute: int = 0  # 0 = unlimited


class ToolPolicyEngine:
    """Engine для policy evaluation."""

    def __init__(self) -> None:
        self._policies: dict[str, ToolPolicy] = {}

    def register(self, policy: ToolPolicy) -> None:
        if policy.tool_name in self._policies:
            logger.warning(
                "ToolPolicyEngine: overwriting policy tool_name=%s",
                policy.tool_name,
            )
        self._policies[policy.tool_name] = policy

    def get(self, tool_name: str) -> ToolPolicy | None:
        return self._policies.get(tool_name)

    def is_allowed(
        self,
        *,
        tool: str,
        agent: str | None = None,
        tenant: str | None = None,
    ) -> bool:
        """Check if tool call is allowed для (agent, tenant).

        Returns:
            True если allowed.
        """
        policy = self._policies.get(tool)
        if policy is None:
            # No policy → deny by default (fail-closed).
            return False
        if policy.allowed_agents and agent not in policy.allowed_agents:
            return False
        if policy.allowed_tenants and tenant not in policy.allowed_tenants:
            return False
        return True

    def requires_approval(self, tool: str) -> bool:
        policy = self._policies.get(tool)
        return policy.requires_approval if policy else False

    def capability_of(self, tool: str) -> ToolCapability | None:
        policy = self._policies.get(tool)
        return policy.capability if policy else None


_engine: ToolPolicyEngine | None = None


def get_tool_policy_engine() -> ToolPolicyEngine:
    global _engine
    if _engine is None:
        _engine = ToolPolicyEngine()
    return _engine


def reset_tool_policy_engine() -> None:
    global _engine
    _engine = None
