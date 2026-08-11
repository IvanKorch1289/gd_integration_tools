"""Policy layer for AI agent tool access control.

S169: Agent Tool Policy — per-agent whitelist/blacklist for tool execution.
Provides auditable, configurable tool permission gates for LangGraph agents.

Usage::

    from src.backend.ai.policy import AgentToolPolicy, ToolPermission  # noqa: F401 — re-export

    policy = AgentToolPolicy(
        agent_id="data_pipeline_agent",
        allowed_tools=["http_request", "sql_query", "file_write"],
        denied_tools=["shell_exec", "delete_file"],
        audit_all=True,
        max_tool_calls_per_run=50,
    )

    result = policy.check("http_request")  # ToolPermission.ALLOW
    result = policy.check("shell_exec")    # ToolPermission.DENY
"""

from src.backend.ai.policy.tool_policy import AgentToolPolicy, ToolPermission


# Round 79: register default AgentToolPolicy в svcs_registry для
# canonical `get_service(AgentToolPolicy)` (тест test_di_factory_returns_default_policy
# требовал эту регистрацию — pre-existing test gap).
# Default policy: empty allowed_tools = default-deny всё (S169 security).
# Production код может override через register_factory() для custom policy.
def _default_tool_policy() -> AgentToolPolicy:
    return AgentToolPolicy(agent_id="default")


try:
    from src.backend.core.svcs_registry import (
        register_factory,
    )

    register_factory(AgentToolPolicy, _default_tool_policy)
except ImportError:  # pragma: no cover — svcs_registry optional
    pass

__all__ = ["AgentToolPolicy", "ToolPermission"]
