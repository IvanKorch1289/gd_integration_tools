# ADR-0065 — LangGraph PostgresCheckpointer + Mem0 как единый long-term memory layer

* Статус: **Accepted** (S29 T12, 2026-05-26 — durable flag + PostgresCheckpointer wrapper)
* Связано с: GAP-2026-05-22 P0-3 (`gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 2), PLAN.md V22.3 §S24, ADR-NEW-18.
* Память: [[feedback_gap_analysis_ai_2026_05_22]], [[feedback_wave_8_rag]].

## Контекст

Действующий memory layer:

1. `src/backend/services/ai/agent_memory.py:39–212` — `AgentMemoryService` на **MongoDB** (TTL 1h short / 30d long, scratchpad).
2. `src/backend/services/ai/langmem_service.py:37+` — `LangMemService` (episodic Postgres + semantic Qdrant + procedural KV).
   - Feature-flag `LANGMEM_ENABLED`, **default-OFF**.
   - `consolidate()` placeholder (Sprint 4 carryover).
3. Extra `[ai-memory]`: `mem0ai`, `langchain-postgres` — **заявлены, не подключены** (grep по `Memory.from_config` пуст).
4. **Нет LangGraph PostgresCheckpointer / RedisCheckpointer** — graph state теряется при рестарте worker.

**Не покрыто**:
* Durable graph state для multi-turn агентов (resume-after-crash).
* Единый координирующий слой между Mongo / Postgres / Qdrant.
* Mem0 OSS как готовая long-term memory с pgvector.

**Риск (H)**: банковский домен, async-агент с multi-turn разговором — kill worker mid-conversation → потеря состояния, нарушение R-V15-11 (leak prevention).

## Решение (Draft)

**Триада: LangGraph Checkpointer + Mem0 + MemoryProtocol**

1. **LangGraph PostgresCheckpointer** (`langgraph-checkpoint-postgres`):
   - Используется как backend для `MultiAgentSupervisor` (multi_agent/supervisor.py).
   - Каждый node-step фиксируется в Postgres с tenant_id + session_id.
   - Resume-after-crash через `app.invoke(input, config={"configurable": {"thread_id": ...}})`.
2. **Mem0 OSS на pgvector**:
   - `Memory.from_config({"vector_store": {"provider": "pgvector", ...}})`.
   - Единый long-term memory layer (поверх legacy LangMem).
   - User-facing API: `memory.add()` / `memory.search()` / `memory.update()` / `memory.delete()` per-user.
3. **Унификация через `MemoryProtocol`** в `core/interfaces/ai_memory.py`:
   - Абстракция over: AgentMemory (Mongo short-term) + Mem0 (pgvector long-term) + LangGraph Checkpointer (durable graph state).
   - Один API для AI-агентов.
   - Per-tenant isolation: namespace = `<tenant_id>:<scope>`.
4. **Migration path** (без breaking):
   - LangMemService → wrapper над Mem0.
   - AgentMemoryService → остаётся для scratchpad (short-term Mongo).
   - LangGraph Checkpointer — новый компонент для multi-agent.

## Альтернативы (отвергнуто на этом этапе)

* **Redis Checkpointer** — быстрее Postgres, но не подходит для compliance audit-trail (нет immutable).
* **In-memory checkpointer** — не durable, нарушает требование.
* **Чисто LangMem без Mem0** — `consolidate()` placeholder требует значимой работы (~3 wave).
* **Чисто Mem0 без LangGraph Checkpointer** — не покрывает graph state recovery.
* **Mongo как primary** — pgvector в Postgres лучше для semantic search + ACID.

## Открытые вопросы (решаются в wave S24 W3)

* **Latency PostgresCheckpointer** — каждый node-step = Postgres write. Bench на multi-turn 20-step разговор (target ≤ 5ms write).
* **Storage volume** — checkpoint snapshots при каждом step могут разрастаться. TTL policy + compression?
* **Tenant isolation** — schema per-tenant vs shared schema + `WHERE tenant_id`?
* **Migration AgentMemory → Mem0** — feature-flag staged rollout или hard cutoff?
* **Mem0 API stability** — Mem0 — молодая библиотека (48k★, но API меняется). Какой commit pinning?

## Зависимости

* `langgraph-checkpoint-postgres>=2.0` [ctx7: langgraph@1.0.8].
* `mem0ai>=0.1.x` [ctx7: mem0@latest].
* `pgvector` (уже в стеке через extensions).
* `asyncpg` (уже в стеке для Postgres async).
* Capability: `ai.memory.read.<tenant>`, `ai.memory.write.<tenant>`, `ai.memory.delete.<tenant>`.

## DoD-критерии scaffold → Accepted

* [ ] PoC LangGraph PostgresCheckpointer на supervisor.py — resume-after-crash работает.
* [ ] Mem0 Memory.from_config({"vector_store": "pgvector"}) подключён.
* [ ] `MemoryProtocol` в `core/interfaces/ai_memory.py`.
* [ ] LangMemService consolidate() реализован через Mem0.
* [ ] AgentMemory feature-flag миграции на Mem0 (default-OFF в S21).
* [ ] Chaos-test: kill worker mid-conversation → resume successful.
* [ ] Latency bench checkpoint write ≤ 5ms p95.
* [ ] Capability `ai.memory.*` в plugin.toml schema.
* [ ] Sphinx page по memory architecture (triade overview).

## Связи с другими ADR

* ADR-0056 (Routes V11) — capability-gate подход одинаков для memory.
* ADR-NEW-16 (Presidio + ru NER) — memory write проходит через PII layer.
* ADR-NEW-S22-followup (Langfuse PII callback) — каждый memory-event логируется (без raw PII).
* Будущий ADR-NEW-19 (Agent orchestration consolidation, P1-6, S25 candidate) — PydanticAI v1.85 + Temporal activity wrapper использует MemoryProtocol.
