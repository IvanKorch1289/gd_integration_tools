"""DSL-процессоры Agent DSL (Sprint 27 W1-W3, S28 W4-W5, S39 W2-W3).

Декларативная агентика поверх :class:`AIGateway` (ADR-NEW-19, S25 W1):

* :class:`AgentRunProcessor` — вызов AIGateway.invoke;
* :class:`AgentBranchProcessor` — verdict-based routing;
* :class:`AgentLoopProcessor` — повтор до stop_condition / max_iterations;
* :class:`AgentParallelProcessor` — fan-out агентов через TaskGroup;
* :class:`AgentGraphProcessor` — LangGraph execution as DSL step (S28 W4).
  Supervisor mode (LLM-driven multi-agent handoff) и ReAct mode.
* :class:`PlanExecuteProcessor` — Plan-and-Execute с verification + replan (S39 W2);
* :class:`ReflectionLoopProcessor` — Generate → Reflect → Refine loop (S39 W3);
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

from src.backend.dsl.engine.processors.agent_dsl.agent_branch import (  # noqa: F401 — re-export
    AgentBranchProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_graph import (  # noqa: F401 — re-export
    AgentGraphProcessor as AgentGraphProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_loop import (  # noqa: F401 — re-export
    AgentLoopProcessor as AgentLoopProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_parallel import (  # noqa: F401 — re-export
    AgentParallelProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_run import (  # noqa: F401 — re-export
    AgentRunProcessor as AgentRunProcessor,
)

# S187: export agent_security_check processor
from src.backend.dsl.engine.processors.agent_dsl.agent_security_check import (  # noqa: F401 — re-export
    AgentSecurityCheckProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.ai_tool_dispatch import (  # noqa: F401 — re-export
    AIToolDispatchProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (  # noqa: F401 — re-export
    GuardrailsApplyProcessor,
)

# S202 fix: export LangGraphAgentProcessor (был orphaned — не в __all__)
from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (  # noqa: F401 — re-export
    LangGraphAgentProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.mcp_tool import (  # noqa: F401 — re-export
    MCPToolProcessor as MCPToolProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (  # noqa: F401 — re-export
    MemoryRecallProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.memory_store import (  # noqa: F401 — re-export
    MemoryStoreProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.pii_mask import (  # noqa: F401 — re-export
    PIIMaskProcessor as PIIMaskProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import (  # noqa: F401 — re-export
    PIIUnmaskProcessor as PIIUnmaskProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.plan_execute import (  # noqa: F401 — re-export
    PlanExecuteProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.reflection_loop import (  # noqa: F401 — re-export
    ReflectionLoopProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.skill_invoke import (  # noqa: F401 — re-export
    SkillInvokeProcessor,
)

__all__: tuple[str, ...] = (
    "AIToolDispatchProcessor",
    "AgentBranchProcessor",
    "AgentGraphProcessor",
    "AgentLoopProcessor",
    "AgentParallelProcessor",
    "AgentRunProcessor",
    "AgentSecurityCheckProcessor",
    "GuardrailsApplyProcessor",
    "LangGraphAgentProcessor",
    "MCPToolProcessor",
    "MemoryRecallProcessor",
    "MemoryStoreProcessor",
    "PIIMaskProcessor",
    "PIIUnmaskProcessor",
    "PlanExecuteProcessor",
    "ReflectionLoopProcessor",
    "SkillInvokeProcessor",
)
