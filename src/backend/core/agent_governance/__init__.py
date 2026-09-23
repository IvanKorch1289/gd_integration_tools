"""Agent Governance — tool policy + plan/approve/execute + execution ledger (Wave 3).

Проблема (EP-R1):
    AI-агенты:
    - Получают слишком широкие права (нет policy gate).
    - Делают side effects напрямую (нет approval).
    - Нет audit trail (кто/что/когда/почему сделал).
    - Могут смешивать данные тенантов (нет isolation).

Решение:
    ``AgentGovernance`` объединяет 4 P0 элемента:

    1. **Tool Policy** (#18) — :class:`ToolPolicyEngine`:
       - Определяет allowed tools per agent/tenant.
       - Capability-based: read vs write vs admin.
       - Side-effect classification.

    2. **Plan → Approval → Execute** (#19):
       - :class:`PlanRegistry` — declarative plans.
       - :class:`ApprovalGate` — operator approval для side-effect actions.
       - :class:`PlanExecutor` — execute after approval.

    3. **Execution Ledger** (#20):
       - :class:`ExecutionLedger` — immutable record каждого tool call.
       - Prompt/model/tool/args/result/approval → 1 execution_id.

    4. **Tenant Memory** (#24):
       - :class:`TenantMemoryStore` — namespace isolation.
       - Retrieval/write требуют tenant_id + access policy.

Использование::

    from src.backend.core.agent_governance import (
        get_tool_policy_engine, get_execution_ledger,
    )

    policy = get_tool_policy_engine()
    if policy.is_allowed(agent="alice", tool="db_write", tenant="t1"):
        result = await execute_tool(...)
        ledger = get_execution_ledger()
        await ledger.record(...)
"""

from __future__ import annotations

from src.backend.core.agent_governance.ledger import (
    ExecutionLedger,
    ExecutionRecord,
    get_execution_ledger,
)
from src.backend.core.agent_governance.policy import (
    ToolCapability,
    ToolPolicy,
    ToolPolicyEngine,
    get_tool_policy_engine,
)

__all__ = (
    "ExecutionLedger",
    "ExecutionRecord",
    "ToolCapability",
    "ToolPolicy",
    "ToolPolicyEngine",
    "get_execution_ledger",
    "get_tool_policy_engine",
)
