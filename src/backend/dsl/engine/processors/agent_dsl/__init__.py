"""DSL-процессоры Agent DSL (Sprint 27 W1-W3, S28 W4-W5).

Декларативная агентика поверх :class:`AIGateway` (ADR-NEW-19, S25 W1):

* :class:`AgentRunProcessor` — вызов AIGateway.invoke;
* :class:`AgentBranchProcessor` — verdict-based routing;
* :class:`AgentLoopProcessor` — повтор до stop_condition / max_iterations;
* :class:`AgentParallelProcessor` — fan-out агентов через TaskGroup;
* :class:`AgentGraphProcessor` — LangGraph execution as DSL step (S28 W4).
  Supervisor mode (LLM-driven multi-agent handoff) и ReAct mode.
* :class:`GuardrailsApplyProcessor` — Llama Guard input/output;
* :class:`PIIMaskProcessor` / :class:`PIIUnmaskProcessor` — reversible PII
  (S25 W4 ADR-NEW-21);
* :class:`SkillInvokeProcessor` — TOML-skill invoke с capability gate;
* :class:`MemoryRecallProcessor` / :class:`MemoryStoreProcessor` — RAG
  / agent memory через :class:`MemoryProtocol` (S24 W3 + S27 W3).
* :class:`MCPToolProcessor` — вызов MCP tool через FastMCP (S27 W3, S28 W5).

Все процессоры наследуются от :class:`BaseAIProcessor` (см. :mod:`._base`),
который инкапсулирует feature-flag + capability-gate + audit-event
boilerplate.

Feature-flag
------------
Все процессоры активируются только при
:data:`feature_flags.ai_agent_dsl_enabled = True` (default-OFF до S27 closure).

См. также
---------
* :mod:`src.backend.dsl.builders.agent_dsl` — fluent Builder mixin.
* docs/adr/0070-agent-dsl-processors.md.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.agent_dsl.agent_branch import (
    AgentBranchProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_graph import (
    AgentGraphProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_loop import AgentLoopProcessor
from src.backend.dsl.engine.processors.agent_dsl.agent_parallel import (
    AgentParallelProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor
from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (
    GuardrailsApplyProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.mcp_tool import MCPToolProcessor
from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (
    MemoryRecallProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.memory_store import (
    MemoryStoreProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.pii_mask import PIIMaskProcessor
from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import PIIUnmaskProcessor
from src.backend.dsl.engine.processors.agent_dsl.skill_invoke import (
    SkillInvokeProcessor,
)

__all__: tuple[str, ...] = (
    "AgentRunProcessor",
    "AgentBranchProcessor",
    "AgentLoopProcessor",
    "AgentParallelProcessor",
    "AgentGraphProcessor",
    "GuardrailsApplyProcessor",
    "PIIMaskProcessor",
    "PIIUnmaskProcessor",
    "SkillInvokeProcessor",
    "MemoryRecallProcessor",
    "MemoryStoreProcessor",
    "MCPToolProcessor",
)
