# AI Agent System — Best Practices (Sprint 170 M3)

> **Важно**: этот документ — reference для разработчиков. **Политики агентов не хранятся здесь** — они в `src/backend/ai/policy/` (tool_policy.py) и `src/backend/core/ai/policy/` (централизованные политики). Этот файл — best practices и usage guidelines, не enforcement.

## Архитектура (12 направлений)

### 1. Multi-provider модели
**Поддерживается**: Perplexity, HuggingFace, OpenWebUI, OpenRouter, Nvidia NIM, OpenAI, **MiniMax** (S170 M3).
**Fallback chain**: настраивается в `config_profiles/*.yml::ai_providers.fallback_chain`.
**Переключение**: через `ai.default_provider` (один из списка).

### 2. Best libraries
- `litellm` — universal LLM gateway (opt-in `[ai]` extra)
- `pydantic-ai` — typed agents
- `httpx` async HTTP
- `orjson` JSON serialization

### 3. Sandbox изоляция
**Агент-генерированный код** исполняется **только** через `core/ai/sandbox.py` (e2b/pyodide).
**Прямой `subprocess.run` запрещён** для AI workflows.

### 4. Prompt storage & versioning
- `services/ai/prompt_registry.py` — registry prompts
- `services/ai/prompt_versioning.py` — A/B testing
- `services/ai/prompts/langfuse_storage.py` — LangFuse backend

### 5-6. DSL для агентов + память
- `dsl/engine/processors/agent_dsl/` — 13 процессоров: agent_run, memory_*, skill_*, mcp_tool, plan_execute, pii_mask, etc.
- Memory: `services/ai/memory/langmem/` (episodic/semantic/procedural/rlm) + mem0 backend
- DSL: `memory_recall`, `memory_store`

### 7. RLM toolkit + token mgmt
- `dsl/engine/processors/ai_rlm.py` — recursive LLM (2512.24601)
- `dsl/engine/processors/llm_structured/` — structured output with token limits
- Goal с ограничениями через `policy/max_iterations` + `policy/max_tokens`

### 8. Централизованные политики
**Не** в `.md`, а в коде:
- `src/backend/ai/policy/tool_policy.py` — tool whitelist/blacklist
- `src/backend/core/ai/policy/spec.py` — policy spec
- `src/backend/core/ai/policy/enforcer/` — runtime enforcement
- `src/backend/core/ai/policy/resolver.py` — capability resolution

### 9. DSL для workflow
13 processors в `agent_dsl/` — каждый со spec_schema, capabilities, async process().

### 10. RAG
- `services/ai/hybrid_rag.py` — BM25 + vector + reranker
- `services/ai/rag_ingest_service.py` — запись
- `services/ai/rag_reindex.py` — переиндексация
- `dsl/engine/processors/duckdb_query.py` + `ingest_file.py` + `documents.py`

### 11. OSINT route (готовый workflow)
**Route**: `routes/osint_agent/route.toml`
**Pipeline** (S170 M3): INN → multi-search (Tavily + Perplexity + scrape) → LLM summarization → structured report.

### 12. Best practices summary
- **Async-first**: все DSL процессоры async
- **Capability-gated**: tool_policy + capability gate на каждом step
- **Sandboxed**: code execution only через e2b
- **PII-masked**: `pii_mask`/`pii_unmask` DSL для чувствительных данных
- **Structured output**: `llm_structured` (pydantic)
- **Traced**: все agent_runs в `gateway_orchestrator` + observability_mixin

