"""DSL-процессоры Agent DSL (Sprint 27 W1-W3).

Декларативная агентика поверх :class:`AIGateway` (ADR-NEW-19, S25 W1):

* :class:`AgentRunProcessor` — вызов AIGateway.invoke;
* :class:`AgentBranchProcessor` — verdict-based routing;
* :class:`AgentLoopProcessor` — повтор до stop_condition / max_iterations;
* :class:`AgentParallelProcessor` — fan-out агентов через TaskGroup;
* :class:`GuardrailsApplyProcessor` — Llama Guard input/output;
* :class:`PIIMaskProcessor` / :class:`PIIUnmaskProcessor` — reversible PII
  (S25 W4 ADR-NEW-21);
* :class:`SkillInvokeProcessor` — TOML-skill invoke с capability gate;
* :class:`MemoryRecallProcessor` / :class:`MemoryStoreProcessor` — RAG
  / agent memory через :class:`MemoryProtocol` (S24 W3 + S27 W3).

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

__all__: tuple[str, ...] = ()
