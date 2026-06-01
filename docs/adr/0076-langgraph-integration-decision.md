# ADR-NEW-25: LangGraph Integration Decision

**Status:** Accepted
**Date:** 2026-05-26
**Authors:** К4
**Sources:** AI Audit 2026-05-26, S28 W4

---

## Context

During the AI Audit (2026-05-26) it was discovered that LangGraph is **already integrated** into the project via two entry points:

1. `services/ai/multi_agent/supervisor.py` — LangGraph StateGraph multi-agent
   supervisor with handoff tools (Sprint 7, ~2 years old). Supervisor node
   routes to sub-agents via `handoff_to_<name>` tools. Supports PostgresSaver
   checkpointer via `langgraph_postgres_saver.py`.

2. `services/ai/ai_graph.py` — ReAct agent via `langgraph.prebuilt.create_react_agent`
   backed by `ChatLiteLLM` → `LiteLLMGateway`. Provides tool-calling loops.

The question was: should LangGraph be **promoted** to a first-class DSL processor
(`.agent_graph(...)`) or kept as an internal implementation detail?

---

## Decision

**LangGraph is kept as an optional execution backend** for specific AI agentic
patterns, exposed as `AgentGraphProcessor` (DSL processor, S28 W4).

This means:
- `langgraph>=0.3.0` stays in `[project.optional-dependencies].ai`
- `langgraph` is **not** removed despite being a large dependency
- `AgentGraphProcessor` wraps existing implementations without reimplementing them
- `langchain-core` / `langchain-community` (unused) are removed from `[ai]`

---

## Rationale

### Why Keep LangGraph

1. **Real integration exists** — `MultiAgentSupervisor` is production code, not scaffold.
   It solves a real problem: LLM-driven multi-agent coordination with handoff tools.

2. **LangGraph solves specific patterns that processor-based DSL lacks:**

   | Pattern | Processor DSL | LangGraph |
   |---|---|---|
   | Conditional branching | `agent_branch` (deterministic if/else) | ✅ conditional_edges (LLM decides) |
   | Tool-use loops | `agent_loop` (blind iteration) | ✅ ReAct via `create_react_agent` |
   | Multi-agent shared state | `agent_parallel` (isolated, no state) | ✅ shared state dict across nodes |
   | Checkpoint / pause-resume | Not supported | ✅ PostgresSaver checkpointer |
   | Human-in-the-loop | `sandbox.py` (NoOp) | ✅ `interrupt` at specific nodes |

3. **Self-hosted compatible** — LangGraph itself has no SaaS component.
   The PostgresSaver checkpointer uses self-hosted PostgreSQL. No managed cloud required.

### Why NOT Make LangGraph the Core

1. **80% of current needs are met by processor-based DSL** — sequential AI
   pipeline, conditional routing, tool execution are all already supported.
   LangGraph adds complexity for edge cases.

2. **LangGraph is a large dependency** (~5MB) — should be opt-in via `extra=[ai]`,
   not forced on everyone.

3. **Current implementations already work** — refactoring `MultiAgentSupervisor`
   or `ai_graph.py` would be unnecessary work.

4. **Not all LangGraph patterns are needed** — no need for the full LangGraph
   ecosystem (memory, prebuilt chains, etc.) when only StateGraph + checkpointing
   + handoff tools are used.

---

## Alternatives Considered

### Option A: LangGraph as Primary Agentic Execution Engine (REJECTED)

Replace processor-based agent DSL with LangGraph as the core execution model.
Would require rewriting `AgentRunProcessor`, `AgentParallelProcessor`, `AgentLoopProcessor`
as LangGraph nodes.

**Rejected because:**
- Overkill: 80% of current patterns don't need graph execution
- Breaking change: existing DSL routes would need rewriting
- Complexity increase: introduces LangGraph graph compilation, checkpointing,
  interrupt handling for all agent routes, not just complex ones

### Option B: Remove LangGraph Entirely (REJECTED)

**Rejected because:**
- `MultiAgentSupervisor` is production code that would need rewriting
- LangGraph checkpointing is the only viable path for pause-resume
- No equivalent open-source alternative for multi-agent with handoff tools

### Option C: LangGraph as Optional DSL Processor (SELECTED)

Wrap existing LangGraph implementations as `AgentGraphProcessor` — a first-class
DSL step alongside `agent_run`, `agent_parallel`, etc.

**Selected because:**
- Minimal new code: delegates to existing `MultiAgentSupervisor` and `ai_graph.py`
- No breaking changes: existing processor-based agents continue to work
- Clear separation: when `graph_type=supervisor/react` is needed, it's available;
  otherwise use simpler `agent_run` / `agent_parallel`
- Self-hosted compatible: all LangGraph dependencies are self-hosted

---

## Consequences

### Positive
- LangGraph is now accessible via declarative YAML (`.agent_graph(...)`)
- Existing `MultiAgentSupervisor` and `ai_graph.py` gain a DSL front-end
- Checkpointing is accessible via `correlation_id` → `thread_id` mapping
- No new dependencies added (LangGraph was already there)

### Negative
- One more execution path to test and maintain
- Users may be confused about when to use `agent_run` vs `agent_graph`
- LangGraph dependency remains in `[ai]` extra

### Neutral
- `langchain-core` and `langchain-community` are removed from `[ai]`
  (they were never imported despite being declared)
- `mem0ai` and `langmem` are removed from their extras (unused, better
  alternatives exist in-project)

---

## When to Use Each

| Use Case | Processor | LangGraph DSL |
|---|---|---|
| Single LLM call | `agent_run` | — |
| Parallel agents (no shared state) | `agent_parallel` | — |
| Deterministic branching | `agent_branch` | — |
| Iterative loop (blind) | `agent_loop` | — |
| **LLM-driven multi-agent with shared state** | — | `agent_graph(graph_type="supervisor")` |
| **ReAct tool-calling loop** | — | `agent_graph(graph_type="react")` |
| **Pause-resume agentic workflow** | — | `agent_graph` + PostgresSaver |
| **Human-in-the-loop approval** | — | `agent_graph` + interrupt |

---

## Implementation (S28 W4)

`AgentGraphProcessor` (`dsl/engine/processors/agent_dsl/agent_graph.py`):
- `graph_type="supervisor"` → delegates to `MultiAgentSupervisor`
- `graph_type="react"` → delegates to `build_and_run_agent` from `ai_graph.py`
- Feature-flag: `ai_agent_dsl_enabled` (inherited from `BaseAIProcessor`)
- Capability: `ai.invoke` (scope = first `workflow_id`)
- Audit event: `ai.agent.graph`
- `thread_id` = `exchange.meta.correlation_id` for checkpointing

No changes to existing `multi_agent/supervisor.py` or `ai_graph.py`.
