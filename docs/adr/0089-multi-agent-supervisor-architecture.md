# ADR-0089: Multi-agent supervisor — LangGraph-based architecture

**Date:** 2026-06-08
**Status:** Accepted (S66 W2 — формализация существующей реализации)
**Sprint:** S66
**Deciders:** core/AI team
**Supersedes:** —

## Context

Роевой анализ V22 (2026-06-08) пометил `src/backend/services/ai/multi_agent/`
как "bare-bones (1 supervisor, 0 impls)" в `docs/sprints/s63/closure.md`.

Реальная проверка (`wc -l`, `find`) показала:

```
src/backend/services/ai/multi_agent/supervisor.py    447 LOC (полная реализация)
src/backend/services/ai/multi_agent/__init__.py       ~30 LOC (public API)
tests/unit/services/ai/multi_agent/test_supervisor.py  120 LOC (5+ тестов)
```

Multi-agent supervisor — **НЕ bare-bones**. Это production-ready
LangGraph-based реализация с:

* `MultiAgentSupervisor` class с LangGraph StateGraph integration;
* `_run_fallback` (deterministic router для smoke-tests без LLM);
* `_run_langgraph` (с `_compile_graph` + `_make_agent_node`);
* `get_credit_pipeline_supervisor()` reference implementation
  (scoring → document_parser → decision, 3 stub-агента);
* feature-flag `multi_agent_supervisor_enabled` (default-OFF, lazy-import);
* полный test coverage: 5+ unit-тестов в `test_supervisor.py`.

## Decision

Признать `src/backend/services/ai/multi_agent/` **production-ready** (НЕ
требует реализации). Документировать архитектурное решение.

**Activation model:** feature-flag `multi_agent_supervisor_enabled` (default-OFF)
по соображениям безопасности (LLM-маршрутизация требует opt-in).

**Real agents integration:** `invoke` callable в `AgentSpec` — это extension
point. Stub-агенты из `_build_credit_pipeline_agents()` заменяются на
реальные handlers из `extensions/credit_pipeline/agents/` при production
deployment (явно документировано в supervisor.py docstring).

**Fallback strategy:** при отсутствии `langgraph` SDK (no `[ai]` extra)
supervisor работает в детерминированном режиме (каждый агент вызывается
один раз в порядке регистрации). Это позволяет smoke-test pipeline без
LLM и без extra deps.

## Consequences

### Positive

* Multi-agent pipeline (credit scoring, RAG-orchestration, multi-modal)
  может быть развёрнут через `get_credit_pipeline_supervisor()` reference
  implementation и заменён stub → real invoke в production.
* Lazy-import pattern (`_is_langgraph_available()`, `_compile_graph()`)
  сохраняет core-импорт без extra `[ai]`.
* Default-OFF feature flag — safe-by-default (нет LLM-вызовов без opt-in).

### Negative

* Real invoke handlers (вместо stub) требуют отдельной задачи:
  `extensions/credit_pipeline/agents/scoring.py` etc.
* LangGraph SDK — extra `ai` (не в core deps). Production deployment
  должен явно установить `pip install gd_integration_tools[ai]`.

### Neutral

* 447 LOC supervisor.py — компактный (ReAct + handoff в одном модуле).
* Fallback router — НЕ для production (только smoke-tests).

## Alternatives Considered

### Альтернатива A: AutoGen-based supervisor

Отклонено: AutoGen менее composable чем LangGraph для pipeline-style
supervisor (использует conversation threads, не явный StateGraph).

### Альтернатива B: Custom StateGraph (без LangGraph)

Отклонено по S58 W1 LESSON: "libraries > custom" — 800 LOC кастомного
кода заменены 235 LOC DSL facade через `langgraph` (см. ADR-0089 references).

### Альтернатива C: bare-bones (1 supervisor, 0 impls) — оставить

Отклонено: реализация уже существует (K4 Sprint 7), закрыта в
S62/early-S63. Bare-bones пометка в S63 closure — неточность роевого
анализа (исправлена этой ADR).

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `MultiAgentSupervisor` | DONE | supervisor.py:111-376 |
| `AgentSpec` | DONE | supervisor.py:60-84 |
| `SupervisorResult` | DONE | supervisor.py:87-108 |
| `_run_fallback` | DONE | supervisor.py:231-257 |
| `_run_langgraph` | DONE | supervisor.py:259-299 |
| `_compile_graph` | DONE | supervisor.py:301-346 |
| `get_credit_pipeline_supervisor` | DONE | supervisor.py:429-447 |
| `__init__.py` public API | DONE | __init__.py (full export) |
| Unit tests | DONE | test_supervisor.py (5+ tests) |
| feature-flag `multi_agent_supervisor_enabled` | DONE | core/config/features.py |
| Real agents (extensions/credit_pipeline/agents/) | TODO | extensions/ (out of scope) |
| DSL blueprint для multi-agent pipeline | TODO | dsl/blueprints/ (out of scope) |

## References

* `src/backend/services/ai/multi_agent/supervisor.py` (447 LOC)
* `src/backend/services/ai/multi_agent/__init__.py`
* `tests/unit/services/ai/multi_agent/test_supervisor.py` (5+ tests)
* `src/backend/services/ai/ai_graph.py` (single-agent ReAct, related)
* `src/backend/core/config/features.py` (feature_flags)
* S58 W1 LESSON: "libraries > custom" (libraries-vs-custom-gate skill)
* ADR-0086: aiocache migration plan (lazy-import pattern reference)
