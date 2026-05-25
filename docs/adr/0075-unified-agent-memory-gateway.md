# ADR-0075 — UnifiedAgentMemoryGateway (Protocol + dispatch)

* Статус: **Accepted** (2026-05-25, Phase B Block 4.1 closure).
* Связано с: ADR-0065 (LangGraph Checkpointer + Mem0), PLAN.md V22.4 §S25/S26,
  директива пользователя 2026-05-22 (Block 4 Memory unification).
* Память: [[feedback_phase_a_ai_hardening]], [[feedback_wave_8_rag]].

## Контекст

До Block 4.1 AI memory имела два независимых сервиса с пересекающимся API:

1. **`AgentMemoryService`** (MongoDB) — short-term: conversation messages
   (`agent_memory_messages`), scratchpad (`agent_memory_scratchpad`),
   key-value facts (`agent_memory_facts`) с TTL.
2. **`LangMemService`** (Postgres + Qdrant) — long-term: episodic /
   procedural / semantic с embedding recall + ConsolidationEngine.

Callsites:
* `dsl/engine/processors/ai.py` — некоторые processors зовут
  `agent_memory_service.add_message(...)` напрямую.
* `services/ai/multi_agent/supervisor.py` — direct calls и в short, и в long.
* `services/ai/agents_pydantic/*` — direct calls.

Проблемы:
* **tenant isolation** не enforced на уровне Protocol (каждый callsite
  должен помнить про tenant_id prefix).
* **Routing decision** дублируется по callsites: "куда писать?" — short
  или long? — решается ad-hoc.
* **Switch backends** для тестов / альтернатив (mem0ai, Redis fallback)
  требует patch всех callsites.

## Решение

### Block 4.1 — Protocol + Gateway

NEW `core/interfaces/agent_memory.py`:

* `AgentMemoryGateway(Protocol, runtime_checkable)` — 8 методов:
  * conversation: `get_messages`, `save_message`;
  * facts: `get_facts`, `save_fact`, `recall_semantic`;
  * scratchpad: `get_scratchpad`, `save_scratchpad`;
  * lifecycle: `consolidate`.
* **`tenant_id: str` обязателен (kw-only) во всех методах**.
* `MemoryMessage` + `MemoryFact` frozen dataclass DTO.

NEW `services/ai/memory_gateway.py::UnifiedMemoryGateway`:

* dispatch short_term (AgentMemoryService) для conversation/scratchpad/kv;
* long_term (LangMemService) для semantic facts + recall;
* `_scope(tenant_id, session_id)` → `"<tenant>:<session>"` namespace prefix
  в Mongo + Qdrant — defense-in-depth multi-tenant isolation;
* graceful degradation при `long_term=None` (recall → [], save_fact
  fallback в short_term kv);
* lazy `app_state_singleton("memory_gateway")` — composition в
  `infrastructure/application/service_setup.py`.

### DoD Block 4.1

* `grep -rn 'AgentMemoryService\b' src/backend/{dsl,services/ai/agents_pydantic,services/ai/multi_agent}` = 0 direct calls (sweep — carryover Block 4.2).
* 14 unit-тестов passing.
* `UnifiedMemoryGateway` удовлетворяет `AgentMemoryGateway` Protocol.

## Альтернативы (отвергнуто)

* **Wrap legacy services через subclass** — нарушает SRP, не даёт чистый
  Protocol для тестовых mock'ов.
* **Single backend (мерж Mongo + Qdrant)** — несовместимы по TTL semantics
  (Mongo TTL on write, Qdrant — manual cleanup).
* **DI через FastAPI Depends** — Streamlit/CLI/Workflow вне FastAPI runtime;
  app_state_singleton универсален.

## Verification

```bash
uv run pytest tests/unit/services/ai/test_memory_gateway.py -v
# Expected: 14 passed
```

### Block 4.2 sweep (carryover)

После реализации Block 4.2 (consolidation):

```bash
grep -rn 'AgentMemoryService\b' src/backend/{dsl,services/ai/agents_pydantic,services/ai/multi_agent}
# Expected: 0 lines
```

## Migration

* Block 4.1 — backbone (Protocol + Gateway scaffold) — этот ADR.
* Block 4.2 — sweep direct callsites + composition wiring + APScheduler
  consolidation job — carryover.

Existing `AgentMemoryService` остаётся как реализация, но публичные
потребители идут через `AgentMemoryGateway` Protocol. После sweep —
deprecation shim на 1 wave (warn at import), затем cleanup.

## Consequences

### Positive

* Single source of truth для memory routing (short vs long).
* Тестируемость: `Mock(spec=AgentMemoryGateway)` универсально для всех
  callsites.
* tenant_id enforcement на Protocol-уровне — невозможно случайно забыть.
* Easy backend swap для тестов / альтернатив (mem0ai, Redis fallback).
* Graceful degradation gateway сам решает что делать без long_term —
  не падает.

### Negative

* Дополнительный indirection layer — +0.1-0.5ms на каждый memory call.
  Mitigation: hot-path operations (`get_messages`) идут напрямую в Mongo
  через тонкий wrapper, не через AIGateway pipeline.
* Carryover sweep 3 направлений (dsl/processors + multi_agent +
  agents_pydantic) — потенциально 10-20 файлов изменений.
* `consolidate(session_id)` сейчас scaffold (LangMemService.consolidate
  возвращает stub-count) — full impl в Block 4.2.

### Carryover

* Block 4.2 — sweep + APScheduler job + LangMemService.consolidate() impl.
* mem0ai backend integration — Phase D (ADR-NEW-18 LangGraph + Mem0).
* tenant_id propagation через ContextVar — S22 multi-tenancy.

## Связи с другими ADR

* ADR-0065 — LangGraph Checkpointer + Mem0 (Draft, transition to Accepted
  при Block 4.2 wire-up).
* ADR-0066 — AI Gateway facade (memory_gateway resolved через
  app.state, не через AIGateway pipeline).
* ADR-0072 — PII production enforcement (save_message / save_fact должны
  применять PII-sanitize до записи, carryover Phase C).
* ADR-NEW-13 — RPACallPolicy (memory не имеет policy-обёртки, carryover).
