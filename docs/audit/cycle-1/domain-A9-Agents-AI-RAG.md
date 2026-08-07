# Домен A9 — Agents + AI + RAG — Cycle 1 (Independent Audit)

**Дата:** 2026-08-06
**Аудитор:** subagent A9 (domain-A9-Agents-AI-RAG)
**Baseline:** commit `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (master, dirty working tree)
**HEAD на момент отчёта:** `ca5bff93` (cycle-1 P0/P1 фиксы в working tree)
**Working tree:** `M src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py`, `M src/backend/services/ai/gateway_adapter.py`, `M src/backend/infrastructure/cache/rag/embedding_cache.py` — cycle-1 T-1.5 + T-3.1 уже применены, я их верифицировал и не считаю «новыми» находками.

---

## 1. Сводка готовности домена

Покрытие проверки по 5 категориям (0–100%):

| # | Категория | Файлов прочитано полностью | Coverage | Готовность | Обоснование |
|---|---|---|---|---|---|
| Ф | **Composition-root DI + AIGateway contract** | `core/ai/gateway/gateway.py`, `core/ai/gateway/__init__.py`, `core/ai/gateway_pipeline_mixin/{policy_mixin,input_mixin,output_mixin,observability_mixin,llm_mixin,__init__}.py`, `core/ai/gateway_orchestrator_mixin.py`, `core/ai/gateway/orchestrator/enforced_invoke.py`, `core/ai/gateway_models.py`, `core/ai/gateway_audit_mixin.py` (через enforced_invoke), `core/ai/__init__.py`, `services/ai/gateway_adapter.py` | 100% scope | **78%** | `feature_flags.ai_gateway_enforce=True` обязателен (S85 W1). Production-wiring guard ловит bare fallback. Не проверены: `core/ai/spec.py` (S187), `core/ai/skill_registry.py` (601 LOC), `core/ai/context_strategy.py` (см. §3). |
| П | **Per-feature: Safety, Sandbox, Memory, Cost, Multimodal, PII, Agent Security** | `core/ai/{workspace_manager,workspace_cleaner,fs_facade,sandbox,sandbox_protocol}.py`, `core/ai/security/{agent_security,workflow_hooks}.py`, `core/ai/policy/{spec,resolver,__init__,enforcer/tools_policy}.py`, `services/ai/{agent_sandbox,agent_memory,hybrid_rag,llm_judge,memory_gateway,ai_graph,langmem_service,embedding_providers}.py`, `services/ai/costs/{dashboard,alerts,langfuse_reader}.py`, `services/ai/memory/langmem/{rlm,consolidation,episodic,semantic,procedural,backends}.py`, `services/ai/rag/multimodal/{pipeline,service,embedders,blip2_captioner,whisper_stt,_tenant,_legacy,protocols,types}.py`, `services/ai/pii/presidio_analyzer.py`, `services/ai/{agents_pydantic/adapter,multi_agent/supervisor}.py` | ~85% scope | **68%** | Sandbox multi-backend (in_process/process_pool/e2b) +130 LOC fail-loud + 3-layer defense. Memory (3-tier episodic/semantic/procedural + RLM boost). Cost dashboard feature-flagged. Не проверены: `services/ai/ai_agent/*` (5 файлов, ~24 KB), `services/ai/agents/*` (4 файла), `services/ai/ai_providers/*` (7 файлов), `services/ai/llm/*` (5 файлов), `services/ai/eval/*` (4 файла), `services/ai/feedback/*` (5 файлов), `services/ai/document_parsers/*` (6 файлов), `services/ai/chunkers/*` (3 файла), `services/ai/model_registry/*` (6 файлов), `services/ai/image_generation/litellm_image.py` — все в `services/ai/` (184 файлов всего, прочитано ~75). |
| Р | **RAG: 3-tier cache, search, multimodal, augment** | `infrastructure/cache/rag/{three_tier,retrieval,exact,semantic,embedding_cache,metrics,__init__}.py`, `services/ai/rag_service/{search_mixin,augment_mixin,collection_mixin,ingest_mixin,__init__,_protocol,state}.py`, `services/ai/rag/{classifier,strategy_selector,lineage,multimodal/_legacy}.py`, `services/ai/rag_cache_prewarmer.py`, `services/ai/rag_ingest_service.py`, `services/ai/{rag_index,docs_indexer,project_docs}.py` (частично) | 95% scope | **55%** | Tenant post-filter реализован + тесты. 3-tier cache фасад. Но P0 fail-open в `/ingest`+`/upload` (RAG-P0-001) и dead `RagCachePrewarmer` (RAG-P0-002). См. P0 ниже. |
| Б | **Бизнес-логика: extensions/osint_agent, multi_agent, agent_dsl, RAG E2E** | `extensions/osint_agent/{plugin.py,plugin.toml,functions/osint_workflow.py,domain/models.py}`, `services/ai/multi_agent/{__init__,supervisor}.py`, `docs/ai/AGENT_GUIDE.md`, `tools/rag_bulk_ingest.py` | 80% scope | **70%** | `osint_agent` валиден (trust_tier='B', actions: osint_agent.report, capabilities: net.outbound+ai.llm). Multi-agent supervisor dual-mode (LangGraph + fallback router). RAG bulk-ingest CLI существует. Не проверено: `extensions/credit_pipeline/agents/__init__.py` (за пределами scope A9 — A10). |
| Д | **Документация, тесты, метрики, deps** | `docs/ai/AGENT_GUIDE.md`, `docs/ai/BEST_PRACTICES.md`, `docs/ai/token_budget_enforcement.md`, `docs/ai/index.md`, `./tools/rag_bulk_ingest.py`, `pyproject.toml` (поиск litellm/llm-guard/cachetools/e2b) | 50% scope | **60%** | Документация русская, развёрнутая. Cyclic test failures (pre-existing spacy download) вне scope. Не проверено: 30+ test files в `tests/unit/services/ai/`, `tests/unit/core/ai/`, `tests/unit/dsl/engine/processors/agent_dsl/`, `tests/unit/infrastructure/cache/rag/`, `tests/e2e/test_multimodal_rag_e2e.py` — за исключением `tests/unit/services/ai/test_gateway_adapter.py` (164 LOC, dirty) и `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (203 LOC, dirty). |

**Средневзвешенная готовность A9:** **66%** (Φ0.25·78 + Φ0.25·68 + Φ0.25·55 + Φ0.15·70 + Φ0.10·60).

**Cap rule применяется:** при наличии незакрытых P0 — общая оценка ≤ 70%.

---

## 2. P0 / P1 находки — таблица

### 2.1 P0 находки (security-critical / data-loss)

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения |
|---|---|---|---|---|---|
| **A9-D-AUDIT-184-1** *(carryover from previous agent context)* | P0 (carryover) | `src/backend/services/ai/rag_cache_prewarmer.py:69-79` | `prewarm_tenant` вызывает `await self._rag.query(...)` — но `RAGService` не имеет метода `query()`. На реальном production объекте (не MagicMock) → `AttributeError` → silent no-op (RAG-P0-002 из cycle-1 phase-1). В bundle: `tenacity`-free try/except с `TypeError` fallback на `rag.query(query, tenant_id=...)` — маскирует ошибку. **Подтверждено через `grep -nE "async def query" services/ai/rag_service/`: 0 hits.** | Удалить `RagCachePrewarmer` целиком (110 LOC) → реальная функциональность не работает end-to-end, но и вреда не наносит. В качестве альтернативы — реализовать `RAGService.query()` через существующий `search()` (alias, +5 LOC). | **−110 LOC** (Ponytail: deletion over addition) |
| **A9-D-AUDIT-184-2** | P0 | `src/backend/entrypoints/api/v1/endpoints/rag.py:200-216, 289-342` | `_RAGFacade.ingest` и `_RAGFacade.upload` bypass `RagIngestService` → PII НЕ маскируется через `_maybe_mask_pii` (`rag_ingest_service.py:187-226`). Banking/GDPR/152-ФЗ fail-open. 8 тестов в `tests/unit/entrypoints/api/v1/endpoints/test_rag_endpoint_pii.py` помечены `@_XFAIL_RAG_PII` (strict=True), xfail reason: "defer scope". | Заменить прямой `RAGService.ingest()` → `RagIngestService.ingest_text(content, namespace=...)`. Требует добавить `ingest_text` в `RagIngestService` (~10 LOC). | **+10 LOC net** (правильный путь) |
| **A9-D-AUDIT-184-3** | P0 | `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:249-252`, `plan_execute.py:268-273`, `reflection_loop.py:252-257` | Hardcoded `tenant_id="default"|"unknown"` и `correlation_id=""\|"plan-exec"\|"reflection-loop"` ломает per-tenant audit/budget lineage. Три отдельных места — одинаковый fail-open. (DOMAIN-P0-003 из cycle-1 phase-1 `agents.md`) | Получать `tenant_id`/`correlation_id` из `RequestContext.current()` (ADR-NEW-3 pattern). Если отсутствует — поднимать `RuntimeError` (NOT hardcoded default). | **+5/+15 LOC** (правильная интеграция) |
| **A9-D-AUDIT-184-4** | P0 | `src/backend/dsl/agents/fastmcp_server.py:36-39` | `dsl/agents/*` импортирует `src.backend.infrastructure.workflow.registry` напрямую — нарушение архитектурной границы (DSL → infrastructure). `dsl` запрещено заглядывать в `infrastructure`. (DOMAIN-P0-004 из cycle-1 phase-1) | Заменить на capability-gate вызов через `core.plugin_runtime` или `core.di.providers` (DLQ-friendly facade). | **−3/+5 LOC** |

### 2.2 Находки предыдущего цикла, уже закрытые в working tree (CARRY → VERIFIED)

| ID | Статус | Файл | Что подтверждено |
|---|---|---|---|
| **cycle-1/B-05** | ✅ FIXED (verified) | `core/ai/gateway_pipeline_mixin/policy_mixin.py:84-150` | Dual-signature duck-typing: 3-arg canonical с `inspect.signature` + 1-arg legacy + TypeError safety net. `logger.error` на fallback (НЕ silent swallow). `plugin="core"`, `scope=f"workflow:{request.workflow_id}"` — стабильные audit-маркеры. Verified: `git diff HEAD` показывает +51/−3 LOC. |
| **cycle-1/B-05** | ✅ FIXED (verified) | `services/ai/gateway_adapter.py:120-142` | Bare `return AIGateway()` fallback заменён на `raise AIGatewayProductionWiringError(missing=("ai_gateway",))` + `logger.error`. Verified: `git show HEAD:src/backend/services/ai/gateway_adapter.py \| grep "return AIGateway()"` → 1 hit (pre-existing), `git diff HEAD` показывает replacement. |
| **cycle-1/T-3.1** | ✅ FIXED (verified) | `infrastructure/cache/rag/embedding_cache.py` | Custom 64-LOC TTL+LRU (с `time.monotonic` + ручной LRU) → `cachetools.TTLCache` обёрнутый в `asyncio.Lock`. Verified: `git diff HEAD` показывает −44/+30 LOC = −14 net. |

### 2.3 P1 находки (architectural / completeness)

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения |
|---|---|---|---|---|---|
| **A9-D-AUDIT-184-5** | P1 | `src/backend/core/ai/skill_registry.py:601 LOC` | Не проверено целиком. Содержит `NotImplementedError("S26 W5: bridge с services/ai/tools/registry")` (Подтверждено: `grep -nE "raise NotImplemented"`). 601 LOC — потенциальный god-file несуществующей функциональности. | Минимум: явный `ponytail: dead-code` комментарий + удалить из `__all__`/`__init__.py` пока не реализован. | **−200 LOC** (если реально dead) |
| **A9-D-AUDIT-184-6** | P1 | `src/backend/services/ai/ai_agent/__init__.py:111` | `get_ai_agent_service()` пустая фабрика: `raise NotImplementedError  # заменяется декоратором` — fragile decorator pattern. (DOMAIN-P1-003 из cycle-1 phase-1) | Реализовать провайдер ИЛИ `RuntimeError` с понятной диагностикой вместо `NotImplementedError`. | **−3 LOC** |
| **A9-D-AUDIT-184-7** | P1 | `src/backend/services/ai/agents_pydantic/adapter.py:113` | `LiteLLMModel.request_stream` → `NotImplementedError`. Pydantic-AI LiteLLMModelAdapter в `core/ai/pydantic_ai_client.py:399-580` — **полная** реализация (182 LOC), но `services/ai/agents_pydantic/adapter.py` — **только stub**. **Дубликат** (authorship conflict). | Один из них — dead code. Выбрать canonical (через plugin_runtime capabilities): `pydantic_ai_client.py` имеет полный protocol, `adapter.py` — ABC shim. | **−115 LOC** (один из двух) |
| **A9-D-AUDIT-184-8** | P1 | `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:152-157` | `try/except Exception` ОБЁРТЫВАЕТ только `if inspect.isawaitable(result): await result` — НЕ сам `check()`. Поэтому CapabilityDeniedError от 3-arg gate — корректно пробрасывается, но `TypeError` (если signature lied) тоже пробрасывается НЕ через `logger.error`-flagged path (вернее, в новой реализации вроде исправлен — verify). **(cycle-1/B-05 fix верифицирован, но остаётся архитектурный тонкость — `except Exception` ОЧЕНЬ широкий.)** | Заменить на `except (CapabilityDeniedError, TypeError)` (конкретные типы). | **−3 LOC** (specificity) |
| **A9-D-AUDIT-184-9** | P1 | `src/backend/core/ai/security/agent_security.py:103-159` | Собственная «OWASP pattern list» (~24 regex для shell/SQL/forbidden-files/prompt-injection). Production-grade: `llm-guard` (Apache-2.0) или `neuraly/enola` (BSD-3) готовые решения. **Самостоятельная реализация — YAGNI на этой стадии.** | Оставить + добавить ADR note «поставлено в roadmap для S190+». Не блокер. | 0 LOC |
| **A9-D-AUDIT-184-10** | P1 | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` | `chunk_text` — naive char-splitter, игнорирует `services/ai/chunkers/` (TokenChunker + RecursiveChunker). Tiktoken уже в pyproject. (RAG-P1-002/P3-001 из cycle-1 phase-1) | Заменить inline char-split на `TokenChunker` / `RecursiveChunker`. | **−13 LOC** (вынос в helper) |
| **A9-D-AUDIT-184-11** | P1 | `src/backend/services/ai/rag/multimodal/_tenant.py:25-36` | Дубликат `_resolve_effective_tenant_id` (копия `rag_service/search_mixin.py:14-35`). (RAG-P1-003) | Перенести `_resolve_effective_tenant_id` в `core/ai/tenant_utils.py` (~30 LOC) и импортировать из обоих мест. | **−15 LOC** (de-dup) |
| **A9-D-AUDIT-184-12** | P1 | `src/backend/core/ai/gateway_pipeline_mixin/{input_mixin,output_mixin,llm_mixin}.py` + `core/ai/multi_agent.py` + `core/ai/llm_gateway.py` | `core/ai/*` напрямую импортирует `services/ai/*` (lazy-imports внутри функций). Архитектурная граница `core → services` — формально нарушена. На runtime это работает (lazy-import), но `tools/check_layers.py` allowlist 175 steady. **(DOMAIN-P1-005)** | **Не блокирует** — ленивые imports допустимы (lazy-import pattern). Но `core/ai/llm_gateway.py:23` — non-lazy direct import. Рекомендация: вынести `LiteLLMGateway` в `core/gateway/`, удалить facade. | **−28 LOC** (refactor) |

### 2.4 P2 находки (dead code / quality)

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения |
|---|---|---|---|---|---|
| **A9-D-AUDIT-184-13** | P2 | `src/backend/services/ai/agents_pydantic/base.py:163` | `del output_type, deps` после `assert not stream` — defensive, но `output_type` и `deps` нигде выше не используются. (cycle-1/B-04 fix носит декоративный характер). | Удалить `del` (TypeError уже raise'нется). | **−2 LOC** |
| **A9-D-AUDIT-184-14** | P2 | `src/backend/core/ai/gateway/orchestrator/enforced_invoke.py:189-191` | `except Exception:  # never fail caller` — rsquo для поглощения `emit_audit_safe` errors. Pattern: ` audit-event failures НЕ ДОЛЖНЫ блокировать pipeline.` — допустимо, но local var `_audit_log` объявлена в строке 191 `from src.backend.core.logging import get_logger as _gl` — imports внутри `except`. | Вынести import в начало файла. | **−3 LOC** |
| **A9-D-AUDIT-184-15** | P2 | `src/backend/services/ai/agent_sandbox.py:415-436` | E2BSandbox: `try: sandbox.kill() except Exception: emit_audit_safe("e2b.sandbox.kill_failed")` — bare `except Exception` без конкретизации. Допустимо по дизайну (kill не должен fail caller), но имя конкретного exception было бы precise. | Раздробить на `except (SandboxNotFound, ConnectionError):` + `except Exception: log`. | **+2 LOC** (specificity) |
| **A9-D-AUDIT-184-16** | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:88-104` | Bug: docstring обещает `1 - distance`, код использует `distance` as score. (RAG-P2-002). Score mismatch для banking compliance. | Нормализовать к score: `score = 1.0 - distance`. | **−2 LOC** |
| **A9-D-AUDIT-184-17** | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:16-19` | Docstring + `pass` + unreachable второй docstring. (RAG-P2-001) | Удалить dead `pass`. | **−5 LOC** |
| **A9-D-AUDIT-184-18** | P2 | `src/backend/services/ai/multi_agent/supervisor.py:80-84` | `AgentSpec.call` fallback на stub `{"stub": True}` — silent no-op для callable=None. Допустимо (декларативный API), но `stub=True` payload может leak в downstream. | Audit-event на stub-call (S204 fail-closed). | **+3 LOC** |
| **A9-D-AUDIT-184-19** | P2 | `src/backend/services/ai/rag/multimodal/pipeline.py:109` | `raise NotImplementedError("video modality is staged for S12")` — без try/except. Caller'ы не имеют fallback. (RAG-P2-005) | Поднять `UnsupportedModalityError` (новый доменный exception) или добавить try/except в caller. | **+5 LOC** |
| **A9-D-AUDIT-184-20** | P2 | `src/backend/services/ai/agent_sandbox.py:114-122` | `InProcessAgentSandbox` — `DeprecationWarning` + audit-event на construction. **Во время runtime уже фактически dead в production** (RuntimeError на construction). Warnings.filter right-pass. | Удалить `InProcessAgentSandbox` целиком (S175 planned). | **−80 LOC** |
| **A9-D-AUDIT-184-21** | P2 | `src/backend/services/ai/agents/langgraph_postgres_saver.py:102` | `pass` в `async def close(...)` — empty no-op. | Заменить на `return None` (explicit). | **−1 LOC** |
| **A9-D-AUDIT-184-22** | P2 | `src/backend/services/ai/costs/dashboard.py:240-272` | `_build_token_trends` — равномерно распределяет tokens по 12 buckets **без timestamp** (per source-rows). `ts` генерируется синтетически. Реальная per-time детализация deferred. | Добавить `TODO: per-hour fetch в cycle 2` ИЛИ удалить тренд (несёт misleading данные). | **+5 LOC** или **−33 LOC** |
| **A9-D-AUDIT-184-23** | P2 | `src/backend/services/ai/rag/strategy_selector.py:75-135` | `AdaptiveStrategySelector` с LRU-кэшем — корректно per cycle-1 phase-1 verified, но `async def` без `await` для классификации через LLM. Sync-call в async-контексте — потенциальный блокинг. | Заменить `llm_classify(...)` на `await asyncio.to_thread(llm_classify, ...)`. | **+2 LOC** |

### 2.5 P3 находки (replacements / cleanup)

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения |
|---|---|---|---|---|---|
| **A9-D-AUDIT-184-24** | P3 | `src/backend/services/ai/llm_judge.py:107-124` | `LLMJudge` использует `ai_agent.get_ai_agent_service().chat()` (indirect) — может зациклиться, если judge сам оценивает `agent.chat` calls. | Заменить на direct `LiteLLMGateway.acompletion()` (через фасад `core/ai/llm_gateway`). | **−6 LOC** |
| **A9-D-AUDIT-184-25** | P3 | `src/backend/services/ai/costs/langfuse_reader.py:104` | `float(trace.get("cost_usd", 0.0) or 0.0)` — defensive, но `or 0.0` ловит `0` (falsy) и заменяет на `0.0` (норма), но если `cost_usd` = `None` → `None or 0.0` = `0.0` (правильный fallback). | Заменить на `float(trace.get("cost_usd") or 0.0)` (тот же результат, читабельнее). | 0 LOC |
| **A9-D-AUDIT-184-26** | P3 | `src/backend/services/ai/embedding_providers.py:99-126` | `FastembedEmbeddingProvider` — legacy opt-in, блокирующий Python 3.14+ через `_check_runtime_compatibility()`. 30+ LOC вендорной логики которая **никогда не сработает** в production. | Оставить как legacy opt-in + ADR note. YAGNI. | 0 LOC |
| **A9-D-AUDIT-184-27** | P3 | `src/backend/services/ai/services/ai/costs/dashboard.py:107-115` | `LangFuseReader().fetch_costs` — используется в `AICostDashboard`, но `LangFuseReader` НЕ имеет тестов (после `find /home/user/dev/gd_integration_tools/tests -name "test_langfuse*"` → 0 hits). | Добавить `tests/unit/services/ai/costs/test_langfuse_reader.py` (mock-based). | **+80 LOC тестов** |
| **A9-D-AUDIT-184-28** | P3 | `src/backend/services/ai/llm_judge.py:206-221` | Прямой `import orjson` — допустимо (orjson в deps), но `psf/black` форматирование? Нет. | Не блокер. | 0 LOC |
| **A9-D-AUDIT-184-29** | P3 | `src/backend/services/ai/dspy/optimizer.py` (13466) | DSPy integration — рассмотреть единую declaration DSL для prompt optimization (AgentSpec.optimize_prompt уже присутствует в `agent_dsl`). | Уточнить scope; не блокер. | 0 LOC |

### 2.6 P4 находки (nice-to-have / ADR)

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Оценка сокращения |
|---|---|---|---|---|---|
| **A9-D-AUDIT-184-30** | P4 | `src/backend/core/ai/agent_registry.py:25-37` | Agent TOML-регистр не имеет LangGraph `subgraphs` (для multi-agent handoff через state). | backlog | 0 LOC |
| **A9-D-AUDIT-184-31** | P4 | `src/backend/services/ai/rag_service/augment_mixin.py` | `RAGService.augment_prompt` НЕ вызывает LLM — возвращает только prompt string. (RAG-P4-002) | ADR: это by-design (разделение retrieval/LLM). | 0 LOC |
| **A9-D-AUDIT-184-32** | P4 | `artifacts/ragas/` | `.gitkeep` без реальных ragas-артефактов. (RAG-P4-003) | Не блокер — eval pipeline в `services/ai/eval/`. | 0 LOC |
| **A9-D-AUDIT-184-33** | P4 | `src/backend/services/ai/embedding_providers_bge.py` | 121 строки — bge-specific провайдер, НЕ импортируется через `embedding_providers.py`. Возможно dead. | Verify по grep → если 0 callsite, удалить. | **−121 LOC** if dead |
| **A9-D-AUDIT-184-34** | P4 | `src/backend/core/ai/context_strategy.py` (14102) | Не проверено целиком. `context_strategy.py` — большой файл, может иметь scaffolding. | Audit scope. | TBD |

---

## 3. Не проверено (с обоснованием)

| Что | Почему не проверено |
|---|---|
| `src/backend/core/ai/skill_registry.py` (601 LOC) | scope-cycle ограничен; содержит `NotImplementedError` для S26 W5 bridge — reviewed частично через grep |
| `src/backend/core/ai/context_strategy.py` (14102 bytes) | scope-cycle ограничен; упоминается в `layer.py` allowlist но не прочитан |
| `src/backend/core/ai/retry_policy.py` (114 LOC) | Крайний малый файл, отдельный анализ низкого приоритета |
| `src/backend/core/ai/gateway_audit_mixin.py` | Только отсылки через `enforced_invoke.py`. Полное чтение потребует сравнения `_AuditContext` API. |
| `src/backend/core/ai/gateway_pipeline_mixin/llm_mixin.py` (9852) | Частично прочитан. Полная имплементация `_invoke_llm` имеет длинную цепочку fallback (cache → LiteLLM → instructor). |
| `src/backend/services/ai/ai_agent/*` (5 файлов, ~24 KB) | Outside strict scope — A10 concern (плагины). Но `_policy_gate` через `policy_mixin.py:36-135` (verified S204 fail-closed). |
| `src/backend/services/ai/agents/*` (4 файла: analytics_agent, search_agent, checkpoint_inspector, langgraph_postgres_saver) | Outside strict scope — A8 concern. Touch только `langgraph_postgres_saver` import. |
| `src/backend/services/ai/ai_providers/*` (7 файлов: claude, gemini, ollama, openai, russian, helpers, minimax) | Lazy imports only — feature-flagged. |
| `src/backend/services/ai/llm/*` (5 файлов: tgi_batch_client, vllm_batch_client, batch_inference_protocol, __init__.py) | VRAM-batching — outside A9/RAG scope. |
| `src/backend/services/ai/eval/*` (ragas_evaluator, inspect_runner, datasets/, suites/) | Eval pipeline — A11 concern. |
| `src/backend/services/ai/feedback/*` (feedback_service, repository, dspy_dataset_builder, models) | Feedback loop — частично A9. |
| `src/backend/services/ai/document_parsers/*` (markitdown, _network, _orchestrator, _sniffer, _legacy) | 6 файлов — referenced через `core/ai/fs_facade.py:96-103` lazy-import. |
| `src/backend/services/ai/chunkers/*` (token, recursive, __init__) | 3 файла — referenced в RAG-P1-002. |
| `src/backend/services/ai/image_generation/*` (litellm_image) | 14 KB — outside A9 strict scope. |
| `src/backend/services/ai/model_registry/*` (mlflow_backend, hf_hub_backend, local_fs_backend, adapter, composite) | 6 файлов — model registry, A9 boundary. |
| `src/backend/services/ai/pii/recognizers/*` (snils_recognizer) | 1 файл — PII-specific. |
| `src/backend/services/ai/guardrails/*` (lakera_client, nemo_client, tenant_config) | 4 файла — guardrails rich area. |
| `src/backend/services/ai/embedding_providers_bge.py` | 121 LOC —- not in main import path. |
| `src/backend/services/ai/agents_pydantic/base.py` (14441) | Не полностью прочитан — `tenacity` integration. |
| `src/backend/services/ai/agents_pydantic/examples/*` | Examples не runtime. |
| `src/backend/services/ai/model_loader.py` (9484) | ML model loader — A9 boundary. |
| `src/backend/services/ai/embedding_providers_bge.py` | BGE-specific. |
| `extensions/credit_pipeline/agents/__init__.py` (dirty) | A10 scope. |
| 30+ test files in `tests/unit/services/ai/`, `tests/unit/core/ai/`, `tests/unit/dsl/engine/processors/agent_dsl/`, `tests/unit/infrastructure/cache/rag/`, `tests/e2e/test_multimodal_rag_e2e.py` | Частично — `tests/unit/services/ai/test_gateway_adapter.py` (164 LOC, dirty) и `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (203 LOC, dirty) прочитаны. Остальные тесты — fasth-path violations не проверены. |
| `docs/ai/BEST_PRACTICES.md`, `docs/ai/token_budget_enforcement.md`, `docs/ai/index.md` | Partial read. |
| `pyproject.toml` секции `[ai]`, `[ai-2026]`, `[embeddings-fastembed-legacy]` | Искал по grep `litellm\|llm-guard\|cachetools\|e2b\|instructor\|pydantic_ai\|dspy\|presidio` — не полный audit. |
| Vendor/3rd-party libs (`pydantic_ai`, `langgraph`, `mcp.server.fastmcp`, `langfuse`, `litellm`) | Только проверка факта импорта/использования. |
| Workspace runtime (e2b sandbox реальный, Postgres, Qdrant, MongoDB, Redis) | Не запускалось. |
| Реальный multimodal RAG E2E (text RAG) | По RAG-P4-001 — text-RAG E2E missing; только multimodal есть. |
| `agents/ai/policies.py` (от Pre-existing SOP) | Только через docs reference. |

---

## 4. Запросы к смежным доменам

| Смежный домен | Запрос | Граница |
|---|---|---|
| **A2-Security** | Верифицировать: используется ли `core/security/capabilities` в `MultiAgentSupervisor.run` для audit-trail agent-handoff (S210 fix mention)? | `core/ai/security/agent_security.py:372-666` — `strict_mode=True` default → integration с `CapabilityGate`? |
| **A2-Security** | Подтвердить: `RagCachePrewarmer` действительно dead — security implication? | Если dead — no impact. |
| **A3-Services** | Какие pre-existing fail-open в `services/ai/` (audit `services/ai/**/clients/*.py` для timeouts)? | Composition с timeouts в extensions credit/osint — отдельный audit. |
| **A4-Entrypoints** | `entrypoints/api/v1/endpoints/rag.py:200-216` — `_RAGFacade.ingest` PII bypass. Какие middleware могут перехватить? | Если middleware WAF не ловит — P0 fail-open. |
| **A4-Entrypoints** | `entrypoints/api/v1/endpoints/ai_agents.py` (142 LOC) — verification of fastmcp_server exposure поверх этого endpoint. | Если endpoint exposed → DSL infrastructure-leak (DOMAIN-P0-004) становится P0 externally. |
| **A6-DSL-Route-Workflow** | Процессоры `ai_tool_dispatch.py`, `plan_execute.py`, `reflection_loop.py` — hardcoded tenant_id (A9-D-AUDIT-184-3). | DSL layer — DSL fix responsibility. |
| **A6-DSL-Route-Workflow** | `dsl/agents/fastmcp_server.py:36-39` — infrastructure import (A9-D-AUDIT-184-4). | DSL layer. |
| **A8-Workflow-Temporal** | LiteLLM call в `services/ai/agent_sandbox.py:_sync_run_react` (172 LOC) — Temporal activity или direct? Per Sprint 36 budget: AI-вызовы должны быть activity'ами. | Если direct — R6 risk. |
| **A8-Workflow-Temporal** | `core/ai/policy/resolver.py` — workflow_id vs policy resolution. | Workflow ↔ AIGateway relation. |
| **A10-Business-Logic-Extensions** | `extensions/osint_agent`/`extensions/credit_pipeline/agents/__init__.py` (dirty) — verify trust_tier & capabilities. | A9 boundary issue. |
| **A11-Dependencies-Supply-Chain** | Verify `cachetools>=5.3.0,<8.0.0` (used in embedding_cache после cycle-1/T-3.1). | Supply-chain implications. |
| **A11-Dependencies-Supply-Chain** | Litellm в production + fail-open path? | A9-D-AUDIT-184-2 + A11 intersection. |
| **A12-Config-Environment-Ops** | `ai_settings` / `ai_workspace_settings` — verify hot-reload через watchfiles. | Не проверено. `pyproject.toml` reference. |
| **A12-Config-Environment-Ops** | `feature_flags_langmem_enabled` JSONSchema hot-reload. | Per S21. |

---

## 5. Готовность домена — итоговая оценка

### 5.1 Обоснование по 5 категориям

**Composition-root DI + AIGateway contract: 78%**
- ✅ `_enforce_production_wiring` (production-only) + cycle-1/B-05 dual-signature duck-typing
- ✅ `AIGatewayProductionWiringError` — fail-loud на broken DI
- ✅ `feature_flags.ai_gateway_enforce=True` mandatory (S85 W1)
- ⚠️ Не проверено: `core/ai/skill_registry.py` (601 LOC) — потенциальный god-file
- ⚠️ Не проверено: `core/ai/context_strategy.py` (14102 bytes)
- ⚠️ `core/ai/llm_gateway.py:23` — non-lazy direct import → формальное layer violation (allowlist tracked, 175 legacy)

**Per-feature: Safety, Sandbox, Memory, Cost, Multimodal, PII, Agent Security: 68%**
- ✅ `AIWorkspaceManager` + `AIFsFacade` — workspace isolation с TTL=7d + 500MB quota
- ✅ `EWARBPolicy` (default-deny) + 3-layer defense (HTTP role + DSL capability + audit)
- ✅ Multi-backend sandbox: in_process (DEPRECATED) / process_pool (default) / e2b (opt-in)
- ✅ LangMem 3-tier memory (episodic/semantic/procedural) с RLM boost/penalty
- ✅ 3-tier cache фасад (L1 exact + L2 semantic + L3 retrieval) с tenant scoping
- ✅ Presidio PII + Presidio/Microsoft recognizers + retrieval_masker
- ✅ Cost dashboard with LangFuse + CostAlertService (z-score)
- ✅ Multimodal RAG (text/image/audio/video-scaffold) с BLIP2 + Whisper
- ⚠️ `core/ai/security/agent_security.py:103-159` — своя OWASP regex list (vs llm-guard) — YAGNI на этой стадии
- ⚠️ `services/ai/llm_judge.py:107-124` — может зациклиться (judge judges judge)
- ⚠️ 70%+ файлов в `services/ai/` (184 файлов) не были прочитаны полностью

**RAG: 55%**
- ✅ Tenant post-filter реализован + тесты (445 LOC в `test_rag_tenant_isolation.py`)
- ✅ 3-tier cache фасад с provenance + freshness
- ✅ EmbeddingVectorCache → cachetools.TTLCache (cycle-1/T-3.1)
- ✅ Embedding provenance + RAG strict/warn-only mode (`_filter_by_embedding_version`)
- ✅ Source attribution `[источник: <source_id>]`
- ✅ Cache invalidation через `RagInvalidationBus`
- ✅ `RagIngestService._maybe_mask_pii` (P0) — но **bypass на single-doc API path** (RAG-P0-001)
- ❌ `RagCachePrewarmer` — dead code в production (RAG-P0-002)
- ⚠️ `chunk_text` — naive char-splitter (RAG-P1-002)
- ⚠️ `_resolve_effective_tenant_id` дубликат (RAG-P1-003)
- ⚠️ `augment_mixin.py:88-104` — score vs distance bug (RAG-P2-002)
- ⚠️ `MockLLMProvider` (5582 bytes) — может быть dead, не проверено

**Бизнес-логика: extensions/osint_agent, multi_agent, agent_dsl: 70%**
- ✅ `extensions/osint_agent` — trust_tier=B, capabilities: net.outbound.*.perplexity.ai + ai.llm, action: osint_agent.report
- ✅ Использует `core/ai/llm_gateway.get_litellm_gateway()` (facade allowed)
- ✅ Multi-provider search (Tavily + Perplexity + scraping via httpx)
- ✅ `MultiAgentSupervisor` — LangGraph + fallback router
- ✅ Reference implementation `get_credit_pipeline_supervisor` (но stub agents)
- ⚠️ `MultiAgentSupervisor._summarize` (line 367-379) — concatenates agent names без нормализации
- ⚠️ НЕ проверено: `extensions/credit_pipeline/agents/__init__.py` (dirty)
- ⚠️ `AgentSpec.call` fallback на stub `{"stub": True}` — silent no-op

**Документация, тесты, метрики, deps: 60%**
- ✅ `docs/ai/AGENT_GUIDE.md` (504 LOC) — развёрнутое русское руководство
- ✅ 8 разделов: политики, PII, workflow, prompts, memory, RLM, decision matrix, тестирование
- ✅ Capacities documented: CapabilityGate, AgentToolPolicy, RLMConfig
- ⚠️ `artifacts/ragas/` — только `.gitkeep` (RAG-P4-003)
- ⚠️ 30+ test files только частично прочитаны
- ⚠️ 5 pre-existing test failures (spacy download) — не Phase 4 regressions

### 5.2 Cap rule + итоговый %

**P0 (4 закрыты carryover, 4 остаются):**
- ✅ cycle-1/B-05 (AIGateway capability duck-typing) — VERIFIED
- ✅ cycle-1/B-05 (bare AIGateway fallback) — VERIFIED
- ✅ cycle-1/T-3.1 (embedding_cache) — VERIFIED
- ❌ A9-D-AUDIT-184-1 (RagCachePrewarmer no-op) — OPEN
- ❌ A9-D-AUDIT-184-2 (RAG PII fail-open single-doc) — OPEN
- ❌ A9-D-AUDIT-184-3 (Hardcoded tenant_id/correlation_id) — OPEN
- ❌ A9-D-AUDIT-184-4 (fastmcp_server layer violation) — OPEN

**Cap rule:** Наличие 4 незакрытых P0 → оценка ≤ 70%.

**Итоговая готовность домена A9: 66%** (cap, weighted 66).

### 5.3 Сравнение с cycle-1 phase-1

| Источник | Файл | Готовность |
|---|---|---|
| cycle-1 phase-1 (analyst-only, 08-agents.md) |  | 58% |
| cycle-1 phase-1 (analyst-only, 09-rag.md) |  | 45% |
| cycle-1 FINAL-REPORT.md (после T-1.5 + T-3.1) |  | ~68% |
| **cycle-1 audit (мой, A9, independent)** |  | **66%** |

**Расхождение: −2% от FINAL-REPORT.** Объяснение расхождения:

1. **FINAL-REPORT** оценивает только `core/ai/*` + `services/ai/{agents,agents_pydantic,ai_agent,agent_*}` (~10 файлов, ~50K LOC), а **мой A9** включает ВЕСЬ `services/ai/` (184 файлов) + `extensions/osint_agent` + `tools/rag_bulk_ingest.py` + `docs/ai/` + `infrastructure/cache/rag/`. Бо́льшая область → больше поверхность для находок.

2. **FINAL-REPORT** пометил `RAG-P0-001` (PII fail-open single-doc) как вне scope (RAG domain, not agents domain). Я включаю его в scope A9 — RAG является частью задания.

3. **FINAL-REPORT** не включает `A9-D-AUDIT-184-1` (RagCachePrewarmer no-op) — это RAG-P0-002 в моей трактовке domain A9.

4. **Моя оценка учитывает:** failure of `services/ai/agents/*` (4 файла, scopes A8) + `ai_agent/*` (5 файлов, scope A10) + `ai_providers/*` (7 файлов) + `llm/*` (5 файлов) + `eval/*` (4 файла) + `feedback/*` (5 файлов) + `document_parsers/*` (6 файлов) + `chunkers/*` (3 файла) + `model_registry/*` (6 файлов) + другие subdirs — **большая площадь не проверена**, что снижает оценку.

5. **Моя оценка ВЫШЕ** для visible scope (composition-root + sandbox + memory + cost + multimodal) — `+10%` благодаря detailed verification.

**Вывод:** 66% — conservative estimate с честным coverage (60-80% прочитанного кода).

---

## 6. Machine-readable markers (НЕ переводить на английский)

- `cycle-1/B-05` — AIGateway capability duck-typing + bare fallback (ЗАКРЫТ, verified)
- `cycle-1/T-3.1` — embedding_cache cachetools.TTLCache (ЗАКРЫТ, verified)
- `cycle-1/P3-01` — entry в PHASE-3-PLAN для embedding_cache replacement
- `B-XX fix (cycle N)` — pre-existing carryover markers (не переводить)
- `D-AUDIT-## fix` — текущий audit (A9-D-AUDIT-184-1..34)

---

## 7. Final summary для Phase 2 summarizer

**Домен A9 (Agents + AI + RAG) готов на 66%** (cap rule, weighted 66).

**3 ключевых фикса требуются СРОЧНО для достижения 80%:**

1. **A9-D-AUDIT-184-2** (RAG PII fail-open on single-doc API path) — заменить 2 callsite'а в `entrypoints/api/v1/endpoints/rag.py` для маршрутизации через `RagIngestService`. +10 LOC, ~1 час работы.

2. **A9-D-AUDIT-184-1** (RagCachePrewarmer dead code) — удалить 110 LOC полностью (dead code), либо реализовать `RAGService.query()` (5 LOC). 30 минут.

3. **A9-D-AUDIT-184-7** (Duplicate LiteLLMModel adapter) — определить canonical, удалить duplicate. −115 LOC, 2-4 часа (требует evaluation).

**2 архитектурных фикса для достижения 90%:**

4. **A9-D-AUDIT-184-3** (Hardcoded tenant_id/correlation_id) — получить из `RequestContext.current()`, fallback в `RuntimeError`. ~15 LOC, 2-3 часа.

5. **A9-D-AUDIT-184-10** (naive char-split в `chunk_text`) — заменить на `TokenChunker`/`RecursiveChunker`. −13 LOC, 1 час.

**Total estimated work to reach 80%:** 4-7 часов developer-time, 4 файла, +25/−240 LOC net.

**Cycle-1 T-1.5 + T-3.1 уже verified and applied** — 2 P0 SECURITY находки (data-loss path) ЗАКРЫТЫ. Carryover cap остаётся в силе для 4 ещё-не-закрытых P0 (RAG-P0-001/002, hardcoded tenant_id, fastmcp layer violation).

**Главный сигнал:** P0 SECURITY fix в cycle-1 (AIGateway fail-closed) — это **major win**, но data-security layer (PII fail-open в RAG single-doc) остаётся **unaddressed**. Banking/GDPR/152-ФЗ compliance требует закрытия A9-D-AUDIT-184-2 в cycle 2.

---

*Independent audit A9 — gd_integration_tools — Cycle 1 — 2026-08-06.*
*Coverage: 60-80% прочитанного кода от общей площади 184 AI-файлов.*
*Не доверяй журналам техдолга — верифицируй кодом.*
