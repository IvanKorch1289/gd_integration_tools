"""Policy layer for AI agent tool access control.

S169: Agent Tool Policy — per-agent whitelist/blacklist for tool execution.
Provides auditable, configurable tool permission gates for LangGraph agents.

Usage::

    from src.backend.ai.policy import AgentToolPolicy, ToolPermission

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

__all__ = ["AgentToolPolicy", "ToolPermission"]
