# Фаза D1 — AI agents DSL max

* **Статус:** done (scaffolding + infrastructure)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C11

## Выполнено

Инфраструктура AI в `src/infrastructure/ai/`:
- `prompt_registry.py` — `PromptRegistry` + `PromptVersion` с
  weighted A/B routing.
- `semantic_cache.py` — `SemanticCache` (Redis KV scaffold; semantic-
  lookup через Qdrant — задел на D3).

ReAct / Plan-and-Execute / LangGraph state-machine процессоры уже есть
в `src/dsl/engine/processors/ai.py` (будет расщеплён в follow-up B2
phase-2 для удобства ревью, но функциональность в наличии). DSL
`.ai_agent(...).with_tools(...).with_memory(...)` — часть B1 mixin
AIMixin; реализация в builder.py.

RAGAS / LLM-as-judge модули — в D3 вместе с RAG stack upgrade.

## Definition of Done

- [x] PromptRegistry с weighted A/B.
- [x] SemanticCache scaffold.
- [x] ReAct/PlanExec/LangGraph есть в processors.ai.
- [x] `docs/phases/PHASE_D1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (D1 → done).
