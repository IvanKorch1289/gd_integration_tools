# Cycle 4 / Phase 2 — Сводный отчёт по доменам

> **Дата:** 2026-08-07
> **HEAD:** `22e08a0d` (cycle-1/2/3 reapply commit)
> **Аналитиков:** 12 (по доменам); Phase 2 — сублимированный read-only обзор
> **Scope:** только Phase-1 отчёты `docs/audit/swarm-2026-08-06/cycle-4/phase-1/01..12-*.md` + `BASELINE.md`
> **Запрещено:** source-код, тесты, git diff/log, cycle-1/2/3 markdown, CLAUDE/PLAN/KNOWN_ISSUES, журналы техдолга
> **Метод:** evidence-preserving cross-domain суммаризация; расхождения между отчётами фиксируются явно как «нужна верификация разработчиком/архитектором»

---

## 1. Executive summary и gate-status

### 1.1 Краткий вердикт

**Phase 4 cycle-4 не готов к прод-промоушену ни в одном из 12 доменов.** Все 12 отчётов фиксируют наличие P0 (security/data-loss/fail-open/race) или P1 (architecture/layer) блокеров; правило «оценка ≥80 запрещена при наличии P0/P1» (per AGENTS.md/BASELINE) срабатывает везде. Суммарно по 12 доменам выявлено **172 findings** (P0: 32, P1: 44, P2: 42, P3: 32, P4: 22). Readiness-scores по доменам (raw) распределены так: `0` — 4 домена (security, services, DSL, RAG), `30` — 2 (infrastructure, business-logic), `34` — 1 (workflow), `36` — 1 (settings), `46` — 1 (agents), `49` — 1 (dependencies), `57` — 1 (entrypoints), `60` — 1 (API).

**Сквозные проблемы** (cross-domain patterns):

1. **Fail-OPEN / fail-silent в security-critical path'ах** (security, services, DSL, API, RAG, business-logic): 9 P0 finding'ов так или иначе про fail-open на критичных путях (auth/tenant/PII/RCE).
2. **Tenant isolation regression drift** (services, business-logic, API, agents): по крайней мере 3 P0 находки (SERV-P0-001, BL-P1-002, AGENTS-P0-005, DOMAIN-P0-005) — несовместимые kwargs / отсутствующий tenant context в multi-tenant путях.
3. **Temporal Worker lifecycle не реализован в проде** (workflow): 4 P0 в workflow-домене (P0-001..P0-004) делают Temporal-путь неработоспособным — `ActivityBridge.decorate()` + `TemporalWorkerPool` не инстанцируются, 4 процессора без `@processor`, `cancel_workflow` fail-open + layer-violation. Эта проблема прямо затрагивает staging/prod profile (dev_light → pg-runner fallback работает).
4. **Cycle-3 T-08 RESIDUAL** (services + business-logic): T-08 «TenantFacade kwargs fix» S193 попытка — ввела новый bug (`tenant_id=`/`principal_id=` вместо `id=`/`principal=`). TenantFacade.with_tenant() поднимает TypeError на каждом вызове в production.
5. **DLQ data-loss / неполный coverage** (infrastructure, entrypoints): B-17 CDC DLQ fix RESOLVED для CDC; MQ (FastStream Redis + RabbitMQ) — entrypoints P0-001/P0-002 RESIDUAL, bare `except Exception` без nack/DLQ-write.
6. **PII fail-OPEN на ingest (RAG) + PII erasure silent fail (DSL)**: разные модули, одинаковый паттерн — sanitize-исключение silently проглатывается, PII остаётся.
7. **defusedxml drop-in неполный** (security, DSL): T-10 cycle-3 был «дефер»; в HEAD остаются минимум 2 точки где stdlib `xml.etree.ElementTree` всё ещё активен (`core/auth/facade.py:490` SAML dev-mode + `dsl/engine/processors/eip/marshal/formats.py:91-140` XmlDataFormat fallback).

### 1.2 Gate-status для 8 правок cycle 1+2+3 (закоммичены в HEAD `22e08a0d`)

> **Контракт BASELINE.md**: 8 правок cycle 1+2+3 уже применены в HEAD. Phase 1 не должен их переоценивать как cycle-4 finding'и. Ниже — статус re-verify, найденный в Phase-1 отчётах.

| Cycle-ID | Скоуп правки | Ожидаемый статус | Фактический статус (по Phase-1 отчётам) | Домен-верификатор | Замечания |
|---|---|---|---|---|---|
| **T-1.4** (multicast + redelivery) | `dsl/engine/processors/eip/routing/multicast`, `reliability/redelivery_policy` | RESOLVED | ✅ **RESOLVED** | DSL (06): 15/15 PASS; Entrypoints (04): упоминается как baseline-verified | BASELINE.md smoke 8/8 PASS; pure-Python 3 syntax, `ExecutionEngine()` без `route_registry` ✓ |
| **T-1.5** (policy_mixin + gateway_adapter) | `dsl/builders/policy_mixin.py` + `services/ai/gateway_adapter.py` | RESOLVED | ✅ **RESOLVED**, но **MUTATED** | Security (02), Agents (08): оба подтверждают fail-closed; но security-домен находит **dead path** (P1-001) — guard существует, но `get_ai_gateway_provider()` никогда не бросает | **RESOLVED** для baseline; **MUTATED** = guard существует, но недостижим из-за composition-time DI |
| **T-3.1** (cachetools.TTLCache) | `infrastructure/cache/backends/memory.py` + JwtBlacklist | RESOLVED | ✅ **RESOLVED** | Infrastructure (01): verified в HEAD; Security (02): `_InMemoryJwtBlacklist._store = TTLCache(10000, 86400)` + `Lock` подтверждено | Никаких residual mutations |
| **T-W1-01** (AuthValidate fail-closed + `AuthenticationProviderUnavailableError`) | `dsl/engine/processors/security.py` | RESOLVED | ✅ **RESOLVED + MUTATED** | DSL (06): 7/7 PASS; cycle-4 post-baseline `c3ff7bec` (canonical `_VERIFIERS_MODULE`); Security (02): import OK + smoke PASS | **MUTATED** = канонический путь переключён с deprecated shim на `core.auth.auth_selector`; post-baseline коммит `baf54d95` дополнительно удалил MCPTool/AgentGraph shadow |
| **T-W1-05** (cdc_routes admin guard + Filewatcher admin guard) | `entrypoints/cdc/cdc_routes.py`, `entrypoints/filewatcher/watcher_routes.py` | RESOLVED | ✅ **RESOLVED** | Entrypoints (04): 4/4 PASS; API (05): verification через `Depends(require_admin((AdminRole.SUPER_ADMIN,)))` на module-level | **RESIDUAL в tests** (entrypoints P1-002): `tests/unit/entrypoints/filewatcher/test_watcher_routes.py:31-145` — 6 pre-existing failures, тесты не используют `app.dependency_overrides[_admin_dep]`. Не атрибутируется рою cycle-4. |
| **T-W1-08** (credit_pipeline `unknown_tenant` branch) | `extensions/credit_pipeline/agents/__init__.py:79-111` | RESOLVED | ✅ **RESOLVED + VERIFIED LIVE** | Business Logic (10): 4/4 PASS live runtime | Никаких residual mutations |
| **T-02** (cycle 3: 4-way CVE enforcement unification) | `tools/pip_audit_gate.py` + `tools/cycle-1-preflight.sh` + `.security/pip-audit-allowlist.txt` | RESOLVED | ✅ **RESOLVED** | Dependencies (11): 27 active CVE-IDs; 8 stale CVE removed (D-AUDIT-02); IGNORED_VULNS frozenset empty | Никаких residual mutations |
| **T-03** (cycle 3: streamlit `<2.0.0` pin + hardcoded shutdown timeout) | `pyproject.toml` + `granian_tuning.py` | RESOLVED | ⚠️ **RESOLVED + RESIDUAL** | Dependencies (11): streamlit `<2.0.0` confirmed (line 137 + 477); Settings (12): **default=30 hardcoded** в `granian_tuning.py:125` — `ENV-P2-001` RESIDUAL | Streamlit pin RESOLVED; hardcoded default RESIDUAL (`graceful_shutdown_timeout: int = Field(default=30, …)`) |
| **T-08** (cycle 3: TenantFacade kwargs fix) | `src/backend/services/tenancy/facade.py:96-124` | RESOLVED per cycle 3 plan | ❌ **RESIDUAL + MUTATED** per Phase 1 | Services (03) SERV-P0-001: confirmed `TypeError: CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'`; Business Logic (10) BL-P1-002: то же подтверждение | **КРИТИЧНО для Phase 3**: правка S193 заменила старый TypeError новым TypeError; test mocks `set_tenant` поэтому не падает; production usage = TypeError. Cycle-3 plan заявлял RESOLVED — Phase-1 фактически опровергает. |

**Итог по 8 правкам:** 5 полностью RESOLVED без residual (T-1.4, T-3.1, T-W1-05, T-W1-08, T-02); 3 с mutations/residual (T-1.5 dead-path, T-W1-01 canonical-path switch, T-03 hardcoded default); **1 КРИТИЧНЫЙ RESIDUAL** (T-08 TenantFacade — broken fix в HEAD, требует немедленного re-fix в Phase 3).

### 1.3 Общий gate-score

| Метрика | Значение |
|---|---|
| Доменов всего | 12 |
| Доменов с P0 | 9 (infrastructure, security, services, entrypoints, API, DSL, workflow, agents, RAG, business-logic) |
| Доменов с P1 | 12 (все) |
| Доменов ready (≥80) | 0 |
| Доменов, не имеющих P0/P1 | 0 |
| Суммарных findings | 172 (P0:32, P1:44, P2:42, P3:32, P4:22) |
| Cross-domain shared blockers | ≥6 (см. executive summary выше) |
| 8 cycle-1+2+3 фиксов RESOLVED | 5 чистых, 2 с MUTATION, 1 RESIDUAL (T-08 — критично) |

---

## 2. Таблица всех 12 доменов

> Каждая строка — один домен из `phase-1/<NN>-<domain>.md`. Readiness, P0..P4 counts, strengths, blockers, residuals, непроверенное — собрано строго из Phase-1 отчётов без дополнительной верификации source.

| # | Домен | Score (raw / cap) | P0 | P1 | P2 | P3 | P4 | Top strengths | Top blockers | Cycle 1+2+3 residuals (status, Phase-1 ID) | Непроверенное / OUT OF SCOPE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | **Infrastructure** | 30 / ≤79 | 3 | 2 | 2 | 3 | 1 | S-1 CDC DLQ fail-loud (B-17); S-2 Outbox multi-instance safety; S-3 Resilience/CB consolidation; S-4 TemporalWorkflowBackend; S-5 OTel 11 instrumentors; S-6 cache.memory TTLCache+Lock (T-3.1) | INFRA-P0-001 (test naming drift `_store` vs `_cache`); INFRA-P0-002 (9 outbox stub arity failures — multi-instance safety untested); INFRA-P0-003 (CDC doc↔test sync) | T-3.1 ✅ RESOLVED (verified in HEAD); T-W1-02 ✅ RESOLVED (B-17 cycle 37); T-W1-03 ⚠️ RESIDUAL (test-infra); T-W1-08 ✅ RESOLVED; T-06 ⚠️ RESIDUAL (capability-gate conftest) | `pyproject.toml`, `uv.lock`, `tools/check_layers_allowlist.txt`, `s3.py`, `extensions/**` |
| 02 | **Security** | 0 / clamp | 3 | 2 | 3 | 2 | 2 | AuthRequiredMiddleware pure ASGI (cycle 43); SecurityHeadersMiddleware; AuthMethod 8-enum; OPA runtime fail-closed (S60 W4); AuthorizationGateway 4-mixin; CapabilityPolicy deny-over-allow; CapabilityGate threading.Lock; 45 tests passed; 0 layer violations | SECURITY-P0-001 (**SAML impersonation через cookie**); SECURITY-P0-002 (**per-workflow SQL policy silently dropped** — `validate_sql` не передаёт context); SECURITY-P0-003 (**xml.etree без defusedxml** в SAML dev-mode) | T-1.5 ✅ RESOLVED (но MUTATED: AIGatewayProductionWiringError dead path); T-W1-01 ✅ RESOLVED; T-1.1 ✅ RESOLVED; T-1.4 ✅ RESOLVED; T-3.1 ✅ RESOLVED; T-02 ✅ RESOLVED; T-03 ✅ RESOLVED | cycle-1 SAML deferred shim carry-over; `infrastructure/security/**`; `extensions/*/auth*`; `entrypoints/api/v1/endpoints/auth_*`; LDAP/SAML реальный bind; runtime feature flags боевые |
| 03 | **Services** | 0 / clamp | 3 | 4 | 7 | 4 | 3 | SV-S-02 IntegrationFacade fail-closed; SV-S-04 ClickHouseAudit 3-tier DLQ; SV-S-05 BrowserCookieStore Fernet; SV-S-09 consistent `ServiceError` pattern; Reverse-layer cleanup сделан (`replay_query.py`); all facades capability-gated | SERV-P0-001 (**TenantFacade.with_tenant TypeError — T-08 RESIDUAL**); SERV-P0-002 (**AdminService fail-OPEN** при gateway=None); SERV-P0-003 (**WebhookRelay DLQ silent-loss** × 3 вектора) | T-08 ❌ **RESIDUAL + MUTATED** (фасад сломан; см. Phase-1 §4.1); T-09 ⚠️ RESIDUAL (через BL-P2-003); cycle-1 P0-001..005 все RESIDUAL per domain; 7 pre-existing JWT test failures в `test_security_facade_jwt.py` | `services/ai/`, `services/security/`, `services/authorization/`, `services/workflows/`; cycle-1/2/3 markdown; real broker integration |
| 04 | **Entrypoints** | 57 / ≤79 | 2 | 4 | 3 | 2 | 1 | W1 T-W1-05 verified (CDC + Filewatcher); W5 watchfiles.awatch rust-based; W6 async-first; W7 module-level `_admin_dep` identity-stable; W8 webhook SSRF+HMAC+rate-limit; SSE PII filter best-effort | ENTRY-P0-001 (**MQ consumer без DLQ** в `invoker_subscribers.py:57-93`); ENTRY-P0-002 (**MQ consumer без DLQ** в `subscribers.py:33,48`) | T-1.2 ⚠️ RESIDUAL (8 xfailed SSE auth propagation = ENTRY-P1-001); T-1.3 ⚠️ RESIDUAL (= ENTRY-P0-001/002); T-W1-03 ⚠️ RESIDUAL; T-W1-07 ⚠️ RESIDUAL (= T-1.2); T-W3-01 ⚠️ RESIDUAL (частично); T-W1-05 ✅ RESOLVED; cycle-3 T-04..T-11 NOT VERIFIED in scope | `entrypoints/api/**`, `entrypoints/middlewares/auth_*`, `entrypoints/middlewares/security/*`; pre-existing filewatcher 6 test failures (= ENTRY-P1-002); Express/MQTT/gRPC/MCP/Soap/GraphQL out of scope; DataQuality B-17 fix not verified (вне scope) |
| 05 | **API** | 60 / clamp ≤60 | 3 | 6 | 1 | 2 | 2 | Pure ASGI middleware chain; router-level RBAC 47/53 endpoints; fail-secure login rate-limit (B-04); DSL ActionSpec builders; no layer violations in scope; 177 passed + 9 xfailed (cycle-4 D-AUDIT) | DOMAIN-P0-001 (**HITL endpoints без permission/tenant**); DOMAIN-P0-002 (**admin_cron RCE** через `importlib.import_module` без whitelist); DOMAIN-P0-003 (**generator/setup.py broken import** `ModuleNotFoundError: src.backend.workflows`) | T-1.1 ✅ RESOLVED (per baseline); T-1.2 ⚠️ RESIDUAL (= DOMAIN-P0-001); T-1.3 ⚠️ RESIDUAL (cross-ref MQ DLQ); T-W1-05 ✅ RESOLVED; API-P0-004 ⚠️ MUTATED (admin_plugins mock-fallback remains); API-P0-005 ⚠️ MUTATED (mobile dead-code isolated); API-P1-001..003 ⚠️ RESIDUAL; API-P2/3/4 NOT VERIFIED | HEAD observed `baf54d95` (≠baseline `22e08a0d`; 3 downstream commits вне scope: MCPTool shadow removal, AuthValidate canonical, eip/reliability.py -442 LOC); pre-existing 4 test failures в `test_auto_register_actions.py`; `extensions/**` |
| 06 | **DSL** | 0 / clamp | 4 | 5 | 4 | 3 | 1 | T-1.4 multicast/redelivery 15/15 PASS; T-W1-08 fail-CLOSED verified; ScanFile fail-closed (`on_threat='fail'`); XXE через `defusedxml` preferred; PII erasure regex whitelist; tenant-aware gate (K-ARCH-4); Exchange finalizers LIFO; Webhook signature HMAC; WAF DSL 23/932/941/942; PipelineValidator | DOMAIN-P0-001 (**XXE через lazy stdlib-fallback** в `XmlDataFormat.unmarshal:91-140`); DOMAIN-P0-002 (**ScriptRunner RCE** — full env leak + no language whitelist); DOMAIN-P0-003 (**PickleDataFormat RCE** в DSL marshal surface); DOMAIN-P0-004 (**PII erasure silent fail-OPEN** в `_delete_vectors`/`_anonymize_db`) | T-1.4 ✅ RESOLVED; T-1.5 ✅ RESOLVED (вне scope); T-3.1 ✅ RESOLVED (вне scope); T-W1-01 ✅ RESOLVED + MUTATED (canonical path switch); T-W1-05 ✅ RESOLVED; T-W1-08 ✅ RESOLVED; T-02/T-03 ✅ RESOLVED; T-1.1 ⚠️ RESIDUAL (вне scope); T-1.2 ⚠️ RESIDUAL; T-1.3 ⚠️ RESIDUAL (= DOMAIN-P0-004 mirror); T-2.1 ⚠️ RESIDUAL частично (web.py/CDCProcessor остаются = DOMAIN-P1-001/P1-005); T-4.1 ⚠️ RESIDUAL (RAG); T-W1-02..04, T-W1-06..07, T-W2-01..04, T-W3-01, T-W4-01 NOT VERIFIED | `extensions/<name>/`; `src/backend/dsl/builders/base/_protocol.py` + transport/* mixin-protocols; `src/backend/dsl/engine/processors/ai/*` + `ai_banking/*` + `rpa/operations/*` + `format_convert/{encodings,specialized}.py`; Workflow/agent_dsl/rag*; post-baseline commits `c3ff7bec`, `e96dda55`, `baf54d95` |
| 07 | **Workflow** | 34 / cap 79 | 4 | 3 | 4 | 4 | 5 | Cycle-1 D-AUDIT-11 flags default-OFF (commit `d9837dc9`, 5/5 False verified); Pydantic discriminated union 12 step types; Cycle-33 restore gateway runtime; Saga `compensate_map` chain-fail (cycle 27 H2); WorkflowRegistry thread-safe; 3 backend profiles (temporal/lite_temporal/pg_runner); `safe_yaml()` отвергает `!!python/object`; StepAuditMiddleware correlation/tenant from ContextVar (S17 K3 W3 D12); 159+171+17+19 passed | DOMAIN-WF-P0-001 (**4 BaseProcessor без @processor decorator** — workflow_convert/subprocess/claim_check/continue_as_new); DOMAIN-WF-P0-002 (**TemporalWorkerPool никогда не instantiated** — `grep = 0 matches`, ADR-045 default=Temporal не работает); DOMAIN-WF-P0-003 (**cancel_workflow fail-OPEN + dsl→services layer violation**); DOMAIN-WF-P0-004 (**worker-handlers (subprocess, claim_check, continue_as_new) unreached в Temporal-кластере**) | D-AUDIT-11 ✅ RESOLVED; D-AUDIT-95 ✅ RESOLVED (14/14 PASS); T-1.5 ✅ RESOLVED (вне scope); B-15 (cycle 37) ✅ RESOLVED (replay правильно mapped); cycle-1 P0-002..P0-004 ⚠️ RESIDUAL (= DOMAIN-WF-P0-001/002/004); cycle-1 P0-005 ⚠️ MUTATED (`_bootstrap_default_declarations` удалён); cycle-1 P1-001/002/003 ✅ RESOLVED | Temporal-кластер реальный (temporalio не установлен → 7 SKIPPED); ClickHouse реальный (StepAuditMiddleware no-op); реальные workflow declarations в плагинах |
| 08 | **Agents** | 46 / cap 79 | 5 | 5 | 4 | 1 | 1 | T-1.5 fail-closed verified (5/5 PASS); BaseAIProcessor template (160/160 tests); AgentSecurityFramework (30/30 tests); AgentSandbox multi-backend (InProcess fail-closed в production); AIAgentService decomposed (5 mixins); PydanticAI typed agents (7/7 tests) | AGENTS-P0-001 (**`get_ai_agent_service()` raises NotImplementedError**); AGENTS-P0-002 (**PIIUnmaskProcessor `_resolve_tokenizer` всегда None**); AGENTS-P0-003 (**GuardrailsApplyProcessor `_resolve_runtime` всегда None** = fail-OPEN safety gate); AGENTS-P0-004 (**LangGraphAgentProcessor bypass BaseAIProcessor template**); AGENTS-P0-005 (**AgentMemoryService no tenant_id** = multi-tenant data breach) | T-1.5 ✅ RESOLVED; gateway_adapter.py:128-129 ⚠️ RESIDUAL (pre-existing baseline, НЕ этому swarm); cycle-3 P0-001/002 ✅ RESOLVED; cycle-3 P0-003 NOT VERIFIED (вне scope); cycle-3 P1-001..002 NOT VIOLATION (layer-checker exit 0); cycle-3 P2-001..002 ⚠️ MUTATED (см. P1-001/P2-002/P2-004 в agents); cycle-3 P3-001 ⚠️ PARTIALLY RESOLVED; cycle-3 P4-001 ⚠️ NOT WIRED | `services/ai/ai_providers/__init__.py` end-to-end; DSPy optimization pipeline; `e2b_code_interpreter` integration; pydantic_ai missing path; LangGraph PostgresSaver real PG; `AgentRegistry` hot_reload call-site; cycle-1/2/3 markdown |
| 09 | **RAG** | 1 / ≤60 | 3 | 1 | 5 | 2 | 2 | S-1 tenant isolation defence-in-depth (20/20 tests); S-2 capability-checked ThreeTierRagCache facade; S-3 fail-closed default (`rag_settings.enabled=False` → 503); S-4 PII fail-closed on retrieval/ingest; S-5 source attribution priority; S-7 emb.version strict-mode gate; S-10 admin endpoints role-gated; S-14 TTL on Redis HASH; 35/35 eval suites + RAGAS | DOMAIN-P0-001 (**multimodal RAG E2E 2 FAIL** — `len(hits) >= 1` got 0 = T-4.1/T-W4-01 RESIDUAL); DOMAIN-P0-002 (**PII fail-OPEN on ingest** при sanitizer failure); DOMAIN-P0-003 (**RagCachePrewarmer runtime phantom** — нет `query()` метода, T-W1-06 RESIDUAL) | T-4.1 ⚠️ RESIDUAL (= DOMAIN-P0-001); T-W1-06 ⚠️ RESIDUAL (= DOMAIN-P0-003); T-W3-01 ⚠️ RESIDUAL (= DOMAIN-P3-001); T-W4-01 ⚠️ RESIDUAL (= DOMAIN-P0-001); T-1.1 ✅ RESOLVED (вне RAG scope); T-W1-04 ✅ RESOLVED; T-08 ✅ RESOLVED (вне scope); T-11 ⚠️ PARTIALLY RESIDUAL (= DOMAIN-P4-001/P4-002); T-06 ⚠️ PARTIALLY RESIDUAL (spacy model download fails) | `services/ai/gateway_adapter.py`; `services/ai/prompts/langfuse_storage.py`; `services/ai/rag/multimodal/**` internal types; pre-existing 2 failures в `test_rag_ingest_service.py`/`test_rag_embedding_version.py` (spacy infra) |
| 10 | **Business Logic** | 30 / cap 79 | 2 | 3 | 4 | 2 | 1 | T-W1-08 credit scoring fail-CLOSED LIVE VERIFIED (4/4 PASS); credit_pipeline actions real implementation (3 handlers); SKB client fail-CLOSED на внешних вызовах; core_entities repository pattern + tenant-aware; DSL workflow saga через builder (3/3 OK); `trust_tier="A"` на банковских extensions; credit_assessment workflow YAML fail-CLOSED default; OSINT INN validation (10-digit checksum); Layer boundaries соблюдены; 83/86 tests passed (96.5%) | BL-P0-001 (**OSINT LLM failure → `raw_text = prompt`** echo); BL-P0-002 (**OSINT search failure → LLM hallucination**); BL-P1-001 (**orders_dsl `.then()` method не существует** → AttributeError runtime crash); BL-P1-002 (**TenantFacade kwargs mismatch** — T-08 RESIDUAL); BL-P1-003 (**validate_inn(None) raises TypeError**) | T-W1-08 ✅ RESOLVED + VERIFIED LIVE; T-08 ❌ **RESIDUAL + MUTATED** (= BL-P1-002); T-09 ⚠️ RESIDUAL (= BL-P2-003); T-1.1 ✅ RESOLVED; T-1.4/T-1.5/T-2.1/T-3.1 ✅ RESOLVED (per BASELINE); T-W1-01..07 NOT VERIFIED (вне scope); T-04/T-05/T-06/T-10 NOT VERIFIED; T-11 NOT VERIFIED | `src/backend/**` кроме контрактных частей; cycle-1/2/3 markdown; pre-existing residuals в `services/ai/gateway_adapter.py:128-129`, `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (НЕ этому swarm); Cross-cutting concerns (security/infra/observability) — другие домены |
| 11 | **Dependencies** | 49 / cap 79 | 0 | 4 | 2 | 3 | 0 | Allowlist 27 active (D-AUDIT-02 applied); Streamlit `<2.0.0` both pins (D-AUDIT-03); 8 stale CVE removed + installed versions ≥ fix; IGNORED_VULNS empty; pip_audit_gate fail-CLOSED синтетически; `make audit-deps` 27× `--ignore-vuln`; Layer checker 175/0; CycloneDX SBOM bumped (PYSEC-2026-87 fix) | DOMAIN-P1-001 (path mismatch `dist/pip-audit.json` vs `pip-audit.json`); DOMAIN-P1-002 (GH CI пропускает 25/27 allowlist CVE); DOMAIN-P1-003 (GitLab CI single-flag + no gate wrapper → потенциальный fail-OPEN); DOMAIN-P1-004 (stale `--ignore-vuln PYSEC-2026-87`) | cycle-3 P0-001..004 ✅ RESOLVED; cycle-3 P1-001 ⚠️ PARTIAL RESIDUAL (3/4 cross-pin duplicates); cycle-3 P2-001 ⚠️ RESIDUAL (dead sphinx ~400 LOC); cycle-3 P2-002 ⚠️ RESIDUAL (phantom-version presidio-ru-recognizers); 8 правок cycle-1+2+3 ✅ VERIFIED via BASELINE | `uv.lock` детально (10 859 строк); network PyPI checks; cycle-3 markdown; `tools/pip_audit_gate.py` сетевой прогон (timeout) |
| 12 | **Settings / Environment** | 36 / cap 79 | 0 | 5 | 3 | 4 | 3 | Multi-source settings loader; CORS fail-closed; ConfigValidator 14 `_check_*` methods; Vault unreachable-flag (no log-spam); ConsulConfig opt-in fail-closed; Granian graceful-shutdown (D-AUDIT-95); 90/90 in-scope tests PASS; K8s manifests production-ready (CPU+mem requests/limits, HPA, PDB, NetworkPolicy); Helm S204 B03 fix | ENV-P1-001 (config_audit stale path `src/core/config/` vs `src/backend/core/config/`); ENV-P1-002 (duplicate Granian surface); ENV-P1-003 (**Redis cluster_mode default=True при пустом cluster_nodes** = broken prod Redis config); ENV-P1-004 (compose без CPU/memory limits); ENV-P1-005 (3 разных env-vars для production detection) | cycle-3 P0-001 ✅ RESOLVED; cycle-3 P0-002 ⚠️ RESIDUAL (= ENV-P2-001); cycle-3 P1-001 ⚠️ RESIDUAL (= ENV-P1-002); cycle-3 P1-002 ⚠️ RESIDUAL (= ENV-P1-001); T-07 ✅ VERIFIED (WorkflowFlags default-OFF); 8 правок cycle-1+2+3 ✅ BASELINE-verified | `.env`, `.env.*`, `secrets/**`; `cycle-{1,2,3}/**`, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`; pre-existing residuals (gateway_adapter.py, test_gateway_pipeline_mixin.py); `extensions/**`, `services/**`, `infrastructure/**` (кроме проверенных); `uv.lock`, `pip-audit.json`, `.blue_green.state` |

---

## 3. Нормализованный реестр findings P0→P4

> Глобальный ключ: `<domain>:<original-id>`. Path/line/evidence скопированы строго из Phase-1 отчётов. Каждый finding получил краткий тег `kind` по приоритету (P0..P4).

### 3.1 P0 — security / data-loss / race / fail-open (32 findings)

| Global key | Original ID | Path:line | Title (one-liner) | Cycle linkage |
|---|---|---|---|---|
| `infrastructure:INFRA-P0-001` | INFRA-P0-001 | `tests/unit/infrastructure/cache/rag/test_embedding_cache.py:128-132` vs `embedding_cache.py:28-34` | Тест `test_defaults_match_baseline` падает: `cache._cache` → `_store` rename не отражён в тесте | new |
| `infrastructure:INFRA-P0-002` | INFRA-P0-002 | `tests/unit/infrastructure/messaging/outbox/test_claim_pending.py:108` + `test_per_row_claim_and_sweeper.py:356` | **9 outbox-stub arity failures**: monkeypatch `lambda: fake_txn` (0 args) vs production `transaction(session)` (1 arg) | new |
| `infrastructure:INFRA-P0-003` | INFRA-P0-003 | `tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py` | CDC doc-test sync: backends помечены `production-ready` в docs, тесты требуют `scaffold` | cycle-1 s7w2 |
| `security:SECURITY-P0-001` | SECURITY-P0-001 | `src/backend/core/auth/auth_selector.py:147-167` | **SAML session trust without validation** — `_verify_saml` принимает любую cookie/header | new (cross-ref cycle-1) |
| `security:SECURITY-P0-002` | SECURITY-P0-002 | `src/backend/services/agent_security/facade.py:121-133` | **Per-workflow SQL policy silently dropped** — `validate_sql` не передаёт `context=` | new (cycle-1 «validate_sql drop» RESIDUAL) |
| `security:SECURITY-P0-003` | SECURITY-P0-003 | `src/backend/core/auth/facade.py:488-493` | **xml.etree без defusedxml** в dev-mode SAML verify (XXE + billion-laughs) | new (cycle-3 T-10 deferred RESIDUAL) |
| `services:SERV-P0-001` | SERV-P0-001 | `src/backend/services/tenancy/facade.py:96-124` | **TenantFacade.with_tenant TypeError** — `CapabilityTenant(tenant_id=, principal_id=)` (неверные kwargs) | **cycle-3 T-08 RESIDUAL + MUTATED** |
| `services:SERV-P0-002` | SERV-P0-002 | `src/backend/services/admin/api.py:97-102` | **AdminService._authorize fail-OPEN** при AuthorizationGateway None | new (cross-ref cycle-3 P0-005) |
| `services:SERV-P0-003` | SERV-P0-003 | `src/backend/services/integrations/webhook_relay.py:262-273, 296-318` | **WebhookRelay DLQ silent-loss** (3 вектора: unbounded _memory_dlq, _dlq_remove swallows LREM, rule_not_found не cleanup) | new |
| `entrypoints:ENTRY-P0-001` | ENTRY-P0-001 | `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` | **MQ consumer без nack/requeue/DLQ** — bare `except Exception` + log, инвойк «успешно принят», reply-канал не зарегистрирован | cycle-1 T-1.3 / cycle-2 T-W1-03 RESIDUAL |
| `entrypoints:ENTRY-P0-002` | ENTRY-P0-002 | `src/backend/entrypoints/stream/subscribers.py:33,48` | **DSL-action MQ consumer без DLQ** — bare except + log для legacy `action_handler_registry` pathway | cycle-1 T-1.3 RESIDUAL |
| `api:DOMAIN-P0-001` | DOMAIN-P0-001 | `src/backend/entrypoints/api/v1/endpoints/hitl.py:24-128` + `services/workflows/hitl_service.py:178-355` | **HITL endpoints без permission/tenant enforcement** — cross-tenant bypass | cycle-1 T-1.2 / cycle-3 API-P0-001 RESIDUAL |
| `api:DOMAIN-P0-002` | DOMAIN-P0-002 | `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:55-94, 109-141` | **admin_cron RCE** через `importlib.import_module` без whitelist (`os:system`, `builtins:exec` match) | cycle-3 API-P0-002 / API-P1-003 RESIDUAL |
| `api:DOMAIN-P0-003` | DOMAIN-P0-003 | `src/backend/entrypoints/api/generator/setup.py:12-14` | **broken import** `from src.backend.workflows.workflows_service import ...` → ModuleNotFoundError; 2/6 handlers unregistered | cycle-2/3 API-P0-003 RESIDUAL |
| `dsl:DOMAIN-P0-001` | DOMAIN-P0-001 | `src/backend/dsl/engine/processors/eip/marshal/formats.py:91-140` | **XXE через lazy stdlib-fallback** в `XmlDataFormat.unmarshal` (defusedxml не hard-import) | cycle-3 T-10 deferred |
| `dsl:DOMAIN-P0-002` | DOMAIN-P0-002 | `src/backend/dsl/engine/processors/script_runner.py:46-152` | **ScriptRunner RCE** — `os.environ` copy в дочерний процесс, default `allowed_languages=None` → все языки | new |
| `dsl:DOMAIN-P0-003` | DOMAIN-P0-003 | `src/backend/dsl/engine/processors/eip/marshal/formats.py:236-272` | **PickleDataFormat RCE** в DSL marshal surface — `pickle.loads(data)  # noqa: S301` | new |
| `dsl:DOMAIN-P0-004` | DOMAIN-P0-004 | `src/backend/dsl/engine/processors/security/pii_erase.py:139-228` | **PII erasure silent fail-OPEN** — `_delete_vectors`/`_anonymize_db` под `except Exception` без `exchange.fail` | new (mirror T-1.3) |
| `workflow:DOMAIN-WF-P0-001` | DOMAIN-WF-P0-001 | `workflow_convert.py:23`, `workflow_subprocess.py:56`, `best_practices/claim_check.py:43`, `best_practices/continue_as_new.py:29` | **4 BaseProcessor без `@processor` decorator** — не регистрируются в `ProcessorRegistry` (verified 72 processors, 4 отсутствуют) | cycle-1 RESIDUAL |
| `workflow:DOMAIN-WF-P0-002` | DOMAIN-WF-P0-002 | `temporal_client.py:227-321` + `activity_bridge.py:288-305` | **`ActivityBridge.decorate()` + `TemporalWorkerPool` не instantiated в production** (`grep = 0 matches`) | cycle-1 RESIDUAL |
| `workflow:DOMAIN-WF-P0-003` | DOMAIN-WF-P0-003 | `src/backend/dsl/engine/processors/cancel_workflow.py:151-169` | **cancel_workflow fail-OPEN + dsl→services layer violation** — silent pass вместо `_logger.warning` | new (cycle-1 cancel RESIDUAL) |
| `workflow:DOMAIN-WF-P0-004` | DOMAIN-WF-P0-004 | `workflow_subprocess.py:24-53`, `best_practices/{claim_check,continue_as_new}.py`, `handlers/continue_as_new_handler.py:76-112` | **Worker-handlers unreached в Temporal-кластере** — `run_workflow_by_id` возвращает `{status:"started"}` marker без реального child execution | cycle-1 RESIDUAL |
| `agents:AGENTS-P0-001` | AGENTS-P0-001 | `src/backend/services/ai/ai_agent/__init__.py:109-111` | **`get_ai_agent_service()` raises `NotImplementedError`** — но registered как factory + referenced из `route_authz`/`llm_judge`/`service_setup` | new |
| `agents:AGENTS-P0-002` | AGENTS-P0-002 | `src/backend/dsl/engine/processors/agent_dsl/pii_unmask.py:165-167` | **`_resolve_tokenizer()` всегда None** — masked PII остаётся masked (round-trip broken) | new |
| `agents:AGENTS-P0-003` | AGENTS-P0-003 | `src/backend/dsl/engine/processors/agent_dsl/guardrails_apply.py:182-185` | **`_resolve_runtime()` всегда None** — content safety fail-OPEN | new |
| `agents:AGENTS-P0-004` | AGENTS-P0-004 | `src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py:57-79` | **LangGraphAgentProcessor overrides `process()` напрямую** — bypass feature_flag + capability + audit-emit | new |
| `agents:AGENTS-P0-005` | AGENTS-P0-005 | `src/backend/services/ai/agent_memory.py:122-128` | **`add_message()` no `tenant_id`** — multi-tenant data breach через Mongo collection без tenant filter (2 XFAIL DEFER-1) | new |
| `rag:DOMAIN-P0-001` | DOMAIN-P0-001 | `tests/e2e/test_multimodal_rag_e2e.py:255-340, 346-397` | **Multimodal RAG E2E 2 FAIL** — `assert len(hits) >= 1` got 0 | cycle-1 T-4.1 / cycle-2 T-W4-01 RESIDUAL |
| `rag:DOMAIN-P0-002` | DOMAIN-P0-002 | `src/backend/services/ai/rag_ingest_service.py:224-226` | **PII fail-OPEN on ingest** — sanitizer failure → raw PII в vector store (test `test_ingest_graceful_on_sanitizer_failure` LOCKS IN behavior) | new |
| `rag:DOMAIN-P0-003` | DOMAIN-P0-003 | `src/backend/services/ai/rag_cache_prewarmer.py:68-80` | **`RagCachePrewarmer` runtime phantom** — `RAGService` не имеет `query()` метода; `prewarm_tenant` возвращает 0; cycle-2 T-W1-06 RESIDUAL | cycle-2 T-W1-06 RESIDUAL |
| `business-logic:BL-P0-001` | BL-P0-001 | `extensions/osint_agent/functions/osint_workflow.py:333-334` | **OSINT LLM fail-OPEN** — `raw_text = prompt` (echo template как report) | new |
| `business-logic:BL-P0-002` | BL-P0-002 | `extensions/osint_agent/functions/osint_workflow.py:307-313` | **OSINT search fail-OPEN** → LLM hallucination без данных | new |

### 3.2 P1 — architecture / layers / authorization / fail-silent guards (44 findings)

| Global key | Original ID | Path:line | Title (one-liner) | Cycle linkage |
|---|---|---|---|---|
| `infrastructure:INFRA-P1-001` | INFRA-P1-001 | `src/backend/infrastructure/observability/otel_auto.py:251-266` + line 134 | Дублирование asyncpg instrumentation (unguarded private `_instrument_asyncpg` vs public `instrument_asyncpg_if_enabled`) | new |
| `infrastructure:INFRA-P1-002` | INFRA-P1-002 | `infrastructure/application/{slo_tracker.py:242-247,vault_refresher.py:248-253}` | Module-level DI-import в середине файла | new |
| `security:SECURITY-P1-001` | SECURITY-P1-001 | `src/backend/services/ai/gateway_adapter.py:114-159` | **AIGatewayProductionWiringError fail-closed guard dead path** — `get_ai_gateway_provider()` не бросает | cycle-3 T-1.5 RESOLVED + MUTATED |
| `security:SECURITY-P1-002` | SECURITY-P1-002 | `core/security/authorization_gateway/__init__.py:357-383` | **`_casbin_check`/`_opa_check` hasattr() dead path** | new |
| `services:SERV-P1-001` | SERV-P1-001 | `services/ops/data_quality/{__init__.py:68-134,...}` | **5-way class duplication**: `DQSeverity`/`DQViolation`/`DQCheckResult`/`DQRule` определены в 5 модулях | new |
| `services:SERV-P1-002` | SERV-P1-002 | `services/io/files.py:1-20` + `services/integrations/skb.py:127-152` | **Reverse-layer shim services→extensions** с `DeprecationWarning` at import-time | new (cycle-1 T-2.1 carry-over) |
| `services:SERV-P1-003` | SERV-P1-003 | `src/backend/services/admin/api.py:58-80` | AdminService `_get_authz` swallows all init exceptions → root cause P0-002 | new |
| `services:SERV-P1-004` | SERV-P1-004 | `src/backend/services/admin/api.py:108-116` | Audit `outcome="error"` несовместимо с downstream `denied` semantic | new |
| `entrypoints:ENTRY-P1-001` | ENTRY-P1-001 | `src/backend/entrypoints/sse/handler.py:188-225` | **`sse_invoke` не пробрасывает `principal`/`permissions`** из `request.state.auth` в `dispatch_action_or_dsl` (8 xfailed) | cycle-1 T-1.2 / cycle-2 T-W1-07 RESIDUAL |
| `entrypoints:ENTRY-P1-002` | ENTRY-P1-002 | `tests/unit/entrypoints/filewatcher/test_watcher_routes.py:31-145` | 6 pre-existing filewatcher test failures (нет `dependency_overrides[_admin_dep]`) | new (post-T-W1-05 drift) |
| `entrypoints:ENTRY-P1-003` | ENTRY-P1-003 | `src/backend/entrypoints/webhook/handler.py:84-127` | webhook management endpoints — `require_auth()` без аргументов (методы аутентификации) | new |
| `entrypoints:ENTRY-P1-004` | ENTRY-P1-004 | `src/backend/entrypoints/webhook/handler.py:155-169` | HMAC signature verify fail-OPEN при отсутствии подписки (`if secret:` short-circuit) | new |
| `api:DOMAIN-P1-001` | DOMAIN-P1-001 | `src/backend/entrypoints/api/generator/setup.py` (whole module) | generator/setup.py dead code (= P0-003) | cycle-3 API-P1-002 RESIDUAL |
| `api:DOMAIN-P1-002` | DOMAIN-P1-002 | `src/backend/entrypoints/api/v1/endpoints/admin_nats.py:64-86` | admin_nats `importlib.import_module` infrastructure → layer-policy (allowlist entry) | cycle-3 API-P1-001 RESIDUAL |
| `api:DOMAIN-P1-003` | DOMAIN-P1-003 | `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:99-230` | admin_actions `_get_registry() → None → mock-fallback` fail-OPEN | new |
| `api:DOMAIN-P1-004` | DOMAIN-P1-004 | `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py:104-301` + `admin_plugins/endpoints.py:104-179` | admin_plugins mock-fallback + 520 LOC legacy duplicate (не mounted) | cycle-2 API-P0-004 MUTATED |
| `api:DOMAIN-P1-005` | DOMAIN-P1-005 | `src/backend/entrypoints/api/mobile/{__init__.py,router.py,schemas.py}` | Mobile BFF dead code (438 LOC, не mounted, DEMO-grade auth) | cycle-2 API-P0-005 MUTATED |
| `api:DOMAIN-P1-006` | DOMAIN-P1-006 | `processors_catalog.py:262-306`, `actions_inventory.py:183-207`, `agent_memory.py`, `notebooks.py` | Information disclosure — нет role-guard; agent_memory tenant xfail | new |
| `dsl:DOMAIN-P1-001` | DOMAIN-P1-001 | `src/backend/dsl/engine/processors/external.py:1-100` (после `baf54d95`) | **CDCProcessor layer violation** dsl→infrastructure | cycle-1 T-2.1 partial RESIDUAL |
| `dsl:DOMAIN-P1-002` | DOMAIN-P1-002 | `src/backend/dsl/engine/processors/function_call.py:194` | `gate.check(...)` ловит `AttributeError → return` (silent fail-OPEN) | new |
| `dsl:DOMAIN-P1-003` | DOMAIN-P1-003 | `src/backend/dsl/engine/processors/scan_file.py:78-120` | `record_metric` в `try/except Exception: pass` — blind spot для AV-покрытия | new |
| `dsl:DOMAIN-P1-004` | DOMAIN-P1-004 | `src/backend/dsl/engine/processors/security/pii_erase.py:60-67` | `entity_type=""` (`:user` split) → `try/except Exception → return 0` (silent) | new |
| `dsl:DOMAIN-P1-005` | DOMAIN-P1-005 | `src/backend/dsl/engine/processors/web.py:19-166` | web automation processors — dsl→services layer violation | new |
| `workflow:DOMAIN-WF-P1-001` | DOMAIN-WF-P1-001 | `dsl/workflow/spec/` (Pydantic discriminated union) vs `infrastructure/workflow/pg_runner_internals/state.py` (7 kinds) | Parallel workflow spec paradigms — no adapter | new |
| `workflow:DOMAIN-WF-P1-002` | DOMAIN-WF-P1-002 | `dsl/engine/processors/cancel_workflow.py:137-174` + `infrastructure/workflow/temporal_backend.py:215-218` | Cancel-workflow phantom-success — `run_id == workflow_id` placeholder | new |
| `workflow:DOMAIN-WF-P1-003` | DOMAIN-WF-P1-003 | `dsl/workflow/compiler/activity_bridge.py:69-77,95-114,132-152` | ActivityBridge lazy AI imports → cold-start tax (100+ MB) | new |
| `agents:AGENTS-P1-001` | AGENTS-P1-001 | `dsl/engine/processors/agent_dsl/__init__.py:60-65` + `bind_skill.py:43-149` | `BindSkillProcessor` orphaned + permanent feature-flag-OFF (`ai_bind_skill_enabled` не registered) | new |
| `agents:AGENTS-P1-002` | AGENTS-P1-002 | `dsl/engine/processors/agent_dsl/*.py` (16 файлов) | **16/17 agent_dsl processors не зарегистрированы через `@processor`** (только `optimize_prompt`) | new |
| `agents:AGENTS-P1-003` | AGENTS-P1-003 | `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:24-26` | Stale docstring «S106 W4 scope: skeleton» — реализация полная | new |
| `agents:AGENTS-P1-004` | AGENTS-P1-004 | `src/backend/core/ai/agent_registry.py:79-81` | Stale docstring «Scaffold-методы поднимают NotImplementedError» — реализация полная | new |
| `agents:AGENTS-P1-005` | AGENTS-P1-005 | `src/backend/services/ai/agents_pydantic/examples/{echo.py,rag_answering.py}` | Examples orphaned — dead reference code | new |
| `rag:DOMAIN-P1-001` | DOMAIN-P1-001 | `src/backend/services/ai/rag_service/augment_mixin.py:90-94` | Citation score contract violation — docstring says `1-distance`, code uses raw `distance` (test `test_rag_citations.py:84` locks in wrong) | new |
| `business-logic:BL-P1-001` | BL-P1-001 | `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,315,316,326,336` | **`.then()` method не существует** → AttributeError при `build_all_order_workflows()` | new |
| `business-logic:BL-P1-002` | BL-P1-002 | `src/backend/services/tenancy/facade.py:116-119` | **TenantFacade.with_tenant kwargs mismatch** (= SERV-P0-001 cross-ref) | cycle-3 T-08 RESIDUAL + MUTATED |
| `business-logic:BL-P1-003` | BL-P1-003 | `src/backend/dsl/helpers/banking.py:31-43` | **`validate_inn(None)` raises TypeError** вместо fail-CLOSED `False` | new |
| `dependencies:DOMAIN-P1-001` | DOMAIN-P1-001 | `tools/pip_audit_gate.py:41` ↔ `make/security.mk:56` | **Path mismatch** CWD vs dist | new (dev-experience) |
| `dependencies:DOMAIN-P1-002` | DOMAIN-P1-002 | `.github/workflows/security.yml:137-138` | **GH CI пропускает 25/27 allowlist CVE** | new (maintenance drift) |
| `dependencies:DOMAIN-P1-003` | DOMAIN-P1-003 | `.gitlab/ci/.gitlab-ci.yml:161` | **GitLab CI single-flag + no gate wrapper** → потенциальный fail-OPEN | new (security fail-open risk) |
| `dependencies:DOMAIN-P1-004` | DOMAIN-P1-004 | `.github/workflows/security.yml:138` | Stale `--ignore-vuln PYSEC-2026-87` (cycle-4 D-AUDIT-02 removed from allowlist) | new (regression mask) |
| `settings:ENV-P1-001` | ENV-P1-001 | `tools/config_audit.py:36`, `tools/codegen_settings.py:62-65,69` | **Stale path** `src/core/config/` vs реальный `src/backend/core/config/` | cycle-3 P1-002 RESIDUAL |
| `settings:ENV-P1-002` | ENV-P1-002 | `main.py:81-117` + `granian_tuning.py:178-225` + `app_base.py:72-163` | **Duplicate Granian surface** — Python API vs CLI builder | cycle-3 P1-001 RESIDUAL |
| `settings:ENV-P1-003` | ENV-P1-003 | `core/config/services/cache.py:201-218` (`RedisSettings.cluster_mode`) | **cluster_mode=True при пустом cluster_nodes=[]** → broken Redis prod | new (data path) |
| `settings:ENV-P1-004` | ENV-P1-004 | `ops/compose/{docker-compose.yml,docker-compose.prod.yml,docker-compose.light.yml,docker-compose.perf.yml,docker-compose.bluegreen.yml,docker-compose.plugin-dev.yml,docker-compose.windows-worker.yml}` | **Ни один service не имеет `deploy.resources.limits`** | cycle-3 P0-002 confirmed |
| `settings:ENV-P1-005` | ENV-P1-005 | `core/config/security.py:115-121`, `profile.py:23`, `base/app_base.py:33-43` | **Три env-vars** (`APP_PROFILE` / `APP_ENV` / `APP_ENVIRONMENT`) для одного концепта | new (consistency) |

### 3.3 P2 — dead code / stubs / observational gaps (42 findings)

| Global key | Original ID | Path:line | Title (one-liner) | Cycle linkage |
|---|---|---|---|---|
| `infrastructure:INFRA-P2-001` | INFRA-P2-001 | `src/backend/infrastructure/repositories/base/base.py:11-70` | 9× `raise NotImplementedError` в ABC (legitimate pattern) | new (informational) |
| `infrastructure:INFRA-P2-002` | INFRA-P2-002 | `src/backend/infrastructure/logging/router.py:57-63` | `RouterLike` is class, не `Protocol` | new |
| `security:SECURITY-P2-001` | SECURITY-P2-001 | `dsl/builders/policy_mixin.py:272-289` | `ResilienceCoordinator.register_*` dead wiring (только `register_from_settings` существует) | new |
| `security:SECURITY-P2-002` | SECURITY-P2-002 | `core/security/authorization_gateway/__init__.py:113` | `_in_memory_policies` dict — без TTL/audit/tenant | new |
| `security:SECURITY-P2-003` | SECURITY-P2-003 | `core/security/authorization_gateway/audit_mixin.py:38` | `except Exception as _:` в audit path (silent suppress) | new |
| `services:SERV-P2-001` | SERV-P2-001 | `src/backend/services/admin/api.py:55-56, 198-244` | `_audit_cb` parameter stored but never used (dead code) | new |
| `services:SERV-P2-002` | SERV-P2-002 | `src/backend/services/tenancy/facade.py:47-58` | `set(ctx)` accepts any object (type-narrow inconsistency) | new |
| `services:SERV-P2-003` | SERV-P2-003 | `services/ops/data_quality/apply_mixin.py:354-356` | `_cardinality_counts` hidden state not in protocol | new |
| `services:SERV-P2-004` | SERV-P2-004 | `services/ops/scheduled_reports.py:166-172` | `run_now` catches all + reports `status="error"` (masks transient) | new |
| `services:SERV-P2-005` | SERV-P2-005 | `services/integrations/webhook_relay.py:222-223` | Local `_HTTPError` class внутри `_send_with_retry` | new |
| `services:SERV-P2-006` | SERV-P2-006 | `services/jupyter/hub_run_orchestrator.py:148-155` | Feature-flag gate masks `ImportError`/`AttributeError` as feature-off | new |
| `services:SERV-P2-007` | SERV-P2-007 | `services/observability/facade.py:67-141` | All observability methods swallow exceptions at DEBUG level | new |
| `entrypoints:ENTRY-P2-001` | ENTRY-P2-001 | `src/backend/entrypoints/stream/{subscribers.py:33-34,49-51,invoker_subscribers.py:89}` | `except Exception` слишком broad | new |
| `entrypoints:ENTRY-P2-002` | ENTRY-P2-002 | `src/backend/entrypoints/filewatcher/watcher_manager.py:172-175` | `_watch_loop` `except Exception` без recovery | new |
| `entrypoints:ENTRY-P2-003` | ENTRY-P2-003 | `src/backend/entrypoints/webhook/handler.py:36-40` | `_require_auth_dep` factory — new function на каждый вызов | new |
| `api:DOMAIN-P2-001` | DOMAIN-P2-001 | `src/backend/entrypoints/api/mobile/*` | Mobile router dead code (= P1-005) | new |
| `dsl:DOMAIN-P2-001` | DOMAIN-P2-002 | `src/backend/dsl/engine/processors/streaming_llm_publishers.py:17-26` | `_BasePublisher` не помечен `ABC` + `@abstractmethod` | new |
| `dsl:DOMAIN-P2-002` | DOMAIN-P2-002 | `src/backend/dsl/engine/processors/fs_directory_scan.py:1-247` | `_DeprecationAuditEmitted` class-level flag не thread-safe | new |
| `dsl:DOMAIN-P2-003` | DOMAIN-P2-003 | `src/backend/dsl/engine/processors/zip_archive.py:135-145` | Feature-flag try/except boilerplate copy-paste (2+ processors) | new |
| `dsl:DOMAIN-P2-004` | DOMAIN-P2-004 | `src/backend/dsl/engine/processors/jdbc_query.py:107-138` | JDBC `params_from='headers'` без whitelist placeholder names | new |
| `workflow:DOMAIN-WF-P2-001` | DOMAIN-WF-P2-001 | `src/backend/dsl/engine/processors/workflow/__init__.py:14-28` | Re-export `Cancel/Invoke/SubWorkflowProcessor` без re-decoration | new |
| `workflow:DOMAIN-WF-P2-002` | DOMAIN-WF-P2-002 | `infrastructure/workflow/pg_runner_backend.py:220-234` | `replay()` всегда `raise NotImplementedError` — pg-runner без Temporal-replay | new (cycle-1 critic flagged) |
| `workflow:DOMAIN-WF-P2-003` | DOMAIN-WF-P2-003 | `infrastructure/workflow/executor/{sub_flow,control_flow,eval,sequential}_mixin.py` (через `__init__.py:188`) | 4 mixin — over-broad except → `StepOutcome.PAUSE` | new |
| `workflow:DOMAIN-WF-P2-004` | DOMAIN-WF-P2-004 | `infrastructure/workflow/{outbox_worker.py,saga_state.py}` | `CompensatingDriverWorker` + `OutboxWorker` — no production-callers | new |
| `agents:AGENTS-P2-001` | AGENTS-P2-001 | `src/backend/dsl/engine/processors/agent_dsl/agent_run.py:195-206` | Unreachable `return None` (при `reraise=True`) | new |
| `agents:AGENTS-P2-002` | AGENTS-P2-002 | `src/backend/core/ai/agent_registry.py:221-239` | `hot_reload` orphaned (no `watchfiles.awatch` integration) | new |
| `agents:AGENTS-P2-003` | AGENTS-P2-003 | `src/backend/services/ai/agent_sandbox.py:164-166` | `InProcessAgentSandbox.shutdown()` → `return None` (misleading docstring) | new |
| `agents:AGENTS-P2-004` | AGENTS-P2-004 | `src/backend/dsl/workflow/orchestrator_engine.py` + `AgentRegistry` | `OrchestratorEngine` orphaned (no instantiation in `src/`) | new |
| `rag:DOMAIN-P2-001` | DOMAIN-P2-001 | `src/backend/services/ai/rag_service/augment_mixin.py:16-19` | Malformed `AugmentMixin` class body (7 items: 2 docstrings + pass + __slots__ + 3 methods) | new |
| `rag:DOMAIN-P2-002` | DOMAIN-P2-002 | `services/ai/rag_service/{ingest,search,collection}_mixin.py:1-12` | Duplicate imports `TYPE_CHECKING` (3 файла × 15 LOC) | new |
| `rag:DOMAIN-P2-003` | DOMAIN-P2-003 | `src/backend/dsl/engine/processors/ai/rag_search.py:18-56` | `RAGSearchProcessor` dead — not exported (конфликт имён с `VectorSearchProcessor`) | new |
| `rag:DOMAIN-P2-004` | DOMAIN-P2-004 | `services/ai/rag_service/augment_mixin.py:3-4,12` | Unused `get_logger` import | new |
| `rag:DOMAIN-P2-005` | DOMAIN-P2-005 | `src/backend/services/ai/rag_query_stats.py:78-89` | Convoluted bytes/str key lookup | new |
| `business-logic:BL-P2-001` | BL-P2-001 | `extensions/core_entities/orders/workflows/orders_dsl.py:37` | Dead import `SagaDeclaration` | new |
| `business-logic:BL-P2-002` | BL-P2-002 | `extensions/osint_agent/tests/test_osint_workflow.py:26` | Invalid 12-digit INN test data (TEST BUG, не code bug) | new |
| `business-logic:BL-P2-003` | BL-P2-003 | `src/backend/core/config/features/plugins.py:41-52` | `credit_pipeline_v2` default=True vs description "default-OFF" (T-09 RESIDUAL) | cycle-3 T-09 RESIDUAL |
| `business-logic:BL-P2-004` | BL-P2-004 | `extensions/core_entities/orders/services/orders.py:112-113,125-126` | Silent ES indexing failures (no `logger.warning`) | new |
| `dependencies:DOMAIN-P2-001` | DOMAIN-P2-001 | `tools/{gen_api_docs.sh,gen_api_autoapi.sh}`, `docs/api/{conf.py,...}`, `pre_prod_check.py:738-741` | Dead sphinx tooling (~400 LOC, 10+ файлов) | cycle-3 P2-001 RESIDUAL |
| `dependencies:DOMAIN-P2-002` | DOMAIN-P2-002 | `pyproject.toml:168` `"presidio-ru-recognizers>=0.1.0,<1.0.0"` | Phantom-version dep — 0 imports в code | cycle-3 P2-002 RESIDUAL |
| `settings:ENV-P2-001` | ENV-P2-001 | `src/backend/core/scaling/granian_tuning.py:125-135` | Hardcoded `graceful_shutdown_timeout: int = Field(default=30, …)` (RESIDUAL) | cycle-3 P0-002 RESIDUAL |
| `settings:ENV-P2-002` | ENV-P2-002 | `src/backend/core/config/services/cache.py` | Layer violation: 2 Settings-класса в одном файле | new |
| `settings:ENV-P2-003` | ENV-P2-003 | `services/{policy,dlq,ldap,mqtt,outbox,rpa,websocket,graphql,llm}.py` + `ai_stack.py` | 12+ Settings не агрегированы в `Settings` aggregator | new |

### 3.4 P3 — library replacement candidates (32 findings)

| Global key | Original ID | Path:line | Title (one-liner) | Cycle linkage |
|---|---|---|---|---|
| `infrastructure:INFRA-P3-001` | INFRA-P3-001 | `src/backend/infrastructure/messaging/outbox/dispatcher.py:276-310` | `OutboxDispatcher._dispatch_one` — custom backoff без `tenacity` (обоснованно) | new |
| `infrastructure:INFRA-P3-002` | INFRA-P3-002 | `src/backend/infrastructure/resilience/reconnection.py:91-122` | Custom reconnect без `tenacity` (обоснованно) | new |
| `infrastructure:INFRA-P3-003` | INFRA-P3-003 | `src/backend/infrastructure/application/slo_tracker.py:30-67` | Custom `_FallbackStats` (list-rebuild) — `statistics.quantiles` candidate | new |
| `security:SECURITY-P3-001` | SECURITY-P3-001 | `src/backend/core/auth/auth_selector.py:178-211` | `_verify_express_jwt` кастомный HS256 — `JwtBackend` через joserfc | new |
| `security:SECURITY-P3-002` | SECURITY-P3-002 | `src/backend/core/auth/auth_selector.py:97-108` | `_verify_basic` кастомный base64 decoder — `HTTPBasic` candidate | new |
| `services:SERV-P3-001` | SERV-P3-001 | `src/backend/services/cache/facade.py:1-165` | Custom cache facade duplicates `cachetools.TTLCache` + `aiocache` | new |
| `services:SERV-P3-002` | SERV-P3-002 | `src/backend/services/io/export_service.py:39-310` | 5 hand-rolled exporters (csv, xlsx, pdf, json, parquet) | new |
| `services:SERV-P3-003` | SERV-P3-003 | `src/backend/services/integrations/webhook_relay.py:160-202` | Custom JMESPath-based transformer | new |
| `services:SERV-P3-004` | SERV-P3-004 | `services/{scheduler/admin.py,cache/metrics.py,messaging/outbox_monitor.py}` | 3 separate thin re-export modules | new |
| `entrypoints:ENTRY-P3-001` | ENTRY-P3-001 | `src/backend/entrypoints/webhook/{registry.py,redis_registry.py}` | Дубликат `WebhookRegistry` + `redis_webhook_registry` (95+100 LOC) | new |
| `entrypoints:ENTRY-P3-002` | ENTRY-P3-002 | `src/backend/entrypoints/stream/invoker_subscribers.py:67-93` | Использует `_deserialize_request` (private leading underscore) | new |
| `api:DOMAIN-P3-001` | DOMAIN-P3-001 | `admin_cron.py:86-94` + `infrastructure/scheduler/scheduler_manager.py:184-218` | `importlib.import_module` + `getattr` — registry-based dispatch candidate | new (related P0-002) |
| `api:DOMAIN-P3-002` | DOMAIN-P3-002 | `entrypoints/middlewares/{api_key.py:71-77,auth_required.py:114-125}` | `APIKeyMiddleware` + `AuthRequiredMiddleware` консолидируемы | new |
| `dsl:DOMAIN-P3-001` | DSL-P3-001 | `dsl/engine/processors/{rate_convert.py:170,geo.py:153,pdf_template.py:154}` | Множество `except Exception: pass` в pass-stub helper'ах | new |
| `dsl:DOMAIN-P3-002` | DSL-P3-002 | `src/backend/dsl/engine/processors/format_convert/data_formats.py:61-64` | Stdlib `ET.fromstring` — mirror of DOMAIN-P0-001 | new |
| `dsl:DOMAIN-P3-003` | DSL-P3-003 | `src/backend/dsl/engine/processors/ai/{cache_processor.py,cachewrite_processor.py,reranker.py}` | `pass`-stubs без логирования | new |
| `workflow:DOMAIN-WF-P3-001` | DOMAIN-WF-P3-001 | `src/backend/dsl/workflow/launcher.py:1-208` | Самописный `WorkflowLauncher` + `packaging.specifiers.SpecifierSet` | new |
| `workflow:DOMAIN-WF-P3-002` | DOMAIN-WF-P3-002 | `step_compilers.py:67-68` + `temporal_backend.py:42-101` | Кастомный `canonical_json_bytes` payload-converter vs `temporalio.converter.DefaultPayloadConverter` | new |
| `workflow:DOMAIN-WF-P3-003` | DOMAIN-WF-P3-003 | `src/backend/dsl/workflow/spec/policies.py:17` | `RetryPolicy` re-export — можно убрать | new |
| `workflow:DOMAIN-WF-P3-004` | DOMAIN-WF-P3-004 | `dsl/engine/processors/workflow/best_practices/claim_check.py:102-104` | `json.dumps(payload, ensure_ascii=False, default=str)` vs `orjson.dumps` | new |
| `agents:AGENTS-P3-001` | AGENTS-P3-001 | `core/ai/agent_spec.py:46-73` (dataclass) vs `dsl/workflow/spec/policies.py:53-71` (Pydantic) | Два `MemoryScope` класса с одинаковым именем | new |
| `rag:DOMAIN-P3-001` | DOMAIN-P3-001 | `services/ai/rag_service/{ingest,search,augment,collection}_mixin.py` | Manual retry/sleep — `tenacity` not applied | cycle-2 T-W3-01 RESIDUAL |
| `rag:DOMAIN-P3-002` | DOMAIN-P3-002 | `src/backend/services/ai/rag_ingest_store.py:139-268` | Custom Redis HASH+ZSET state store (130 LOC) | new |
| `business-logic:BL-P3-001` | BL-P3-001 | `extensions/osint_agent/functions/osint_workflow.py:239,264,275,310,333` | 5× `except Exception` broad catch | new |
| `business-logic:BL-P3-002` | BL-P3-002 | `extensions/credit_pipeline/agents/__init__.py:101-103` | `except Exception: pass` без `logger.warning` в audit emission | new |
| `dependencies:DOMAIN-P3-001` | DOMAIN-P3-001 | `pyproject.toml:{137 vs 477, 81 vs 628, 281 vs 509}` | Cross-pin duplicates (streamlit/lxml/pillow) | cycle-3 P1-001 PARTIAL RESIDUAL |
| `dependencies:DOMAIN-P3-002` | DOMAIN-P3-002 | `tools/verify_pypi_versions.py:79-83` | `_parse_pin` возвращает LOWER bound вместо UPPER | new |
| `dependencies:DOMAIN-P3-003` | DOMAIN-P3-003 | `pyproject.toml:558` `"deptry>=0.20,<1.0"` | Dead dev-dep | new |
| `settings:ENV-P3-001` | ENV-P3-001 | `src/backend/core/config/services/cache.py:201-218` | `cluster_mode` default/example/description drift | new (related P1-003) |
| `settings:ENV-P3-002` | ENV-P3-002 | `src/backend/core/config/waf.py:49-57` | `outbound_via_facade: bool = Field(default=True)` — not security-relevant | new |
| `settings:ENV-P3-003` | ENV-P3-003 | `src/backend/core/config/transport.py:20-43` | `TransportSettings` использует `BaseSettings` напрямую | new |
| `settings:ENV-P3-004` | ENV-P3-004 | `src/backend/core/config/ai_stack.py` | 9 несвязанных Settings в одном файле | new |

### 3.5 P4 — organic feature candidates (22 findings)

| Global key | Original ID | Path:line | Title (one-liner) | Cycle linkage |
|---|---|---|---|---|
| `infrastructure:INFRA-P4-001` | INFRA-P4-001 | — | Organic feature: typed DLQ replay API для failed-events в CDC | cycle-2 T-W1-02 deferred |
| `security:SECURITY-P4-001` | SECURITY-P4-001 | `src/backend/core/auth/__init__.py:76-98` | `AuthMethod.OIDC` отсутствует (S126+ carryover) | cycle-1 carry-over |
| `security:SECURITY-P4-002` | SECURITY-P4-002 | `src/backend/core/auth/auth_selector.py:147-167` | Per-request session revocation в SAML path (SLO) | new |
| `services:SERV-P4-001` | SERV-P4-001 | `services/ops/data_quality/` | Persistent storage DQ rules (Camel-style configurator) | new |
| `services:SERV-P4-002` | SERV-P4-002 | `services/rpa/` | Structured retry policy per RPA action | new |
| `services:SERV-P4-003` | SERV-P4-003 | `services/admin/api.py:199-221` | `AdminService.get_audit_log` stub (always `[]`) | new |
| `entrypoints:ENTRY-P4-001` | ENTRY-P4-001 | `entrypoints/stream/` | DSL-action `action_handler_registry` pathway — legacy vs invoker | new |
| `api:DOMAIN-P4-001` | DOMAIN-P4-001 | `entrypoints/api/generator/{specs.py,auto_register.py}` | OpenAPI `x-action-id` extension export | new |
| `api:DOMAIN-P4-002` | DOMAIN-P4-002 | `dsl/commands/setup/orchestrator.py` | Tenacity library replacement для DSL retry (related T-W3-01) | cycle-3 T-W3-01 deferred |
| `dsl:DOMAIN-P4-001` | DOMAIN-P4-001 | `src/backend/dsl/engine/processors/` | Camel/Airflow ControlBus coverage gap (WireTap есть, IdempotentConsumer есть) | new |
| `workflow:DOMAIN-WF-P4-001` | DOMAIN-WF-P4-001 | `dsl/workflow/{dryrun.py:13-14,bpmn_importer.py:18-19}` | Нет reverse path BPMN XML export | new |
| `workflow:DOMAIN-WF-P4-002` | DOMAIN-WF-P4-002 | `infrastructure/workflow/versioning/worker_versioning.py:145-159` | `should_route_to_this_version` dead (vs native `ramp_percentage`) | new |
| `workflow:DOMAIN-WF-P4-003` | DOMAIN-WF-P4-003 | `step_compilers.py:67-68`, `compile_reflect_step.py:547/551` | Magic-numbers в step-compilers | new |
| `workflow:DOMAIN-WF-P4-004` | DOMAIN-WF-P4-004 | `dsl/workflow/{bpmn_importer.py:1-535,visualize.py:1-460}` | BPMN importer + visualize default-OFF (cycle 33 restore) | new |
| `workflow:DOMAIN-WF-P4-005` | DOMAIN-WF-P4-005 | `services/workflows/cost_estimator.py:1-236` | Cost-based cancellation extension (Camunda CostDecisions analog) | new |
| `agents:AGENTS-P4-001` | AGENTS-P4-001 | `core/ai/security/agent_security.py` + `services/agent_security/facade.py` + `agent_security_check.py` | `AgentSecurityFramework` изолирован — нет consumer'ов в extensions | cycle-3 T-11 deferred |
| `rag:DOMAIN-P4-001` | DOMAIN-P4-001 | `src/backend/services/ai/rag_query_stats.py:43-64` | `RagQueryStatsCollector` — no Prometheus metrics | cycle-3 T-11 deferred |
| `rag:DOMAIN-P4-002` | DOMAIN-P4-002 | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` | Naive sliding-window chunker (vs `RecursiveCharacterTextSplitter`) | cycle-3 T-11 deferred |
| `business-logic:BL-P4-001` | BL-P4-001 | `extensions/credit_pipeline/workflows/{multi_agent_supervisor,code_interpreter_loop,rag_augmented_saga}.workflow.yaml` | 3 YAML workflow без runtime-loaders | new |
| `settings:ENV-P4-001` | ENV-P4-001 | `src/backend/core/config/services/dlq.py:44-51` | `DLQCleanupSettings.enabled: bool = Field(default=True)` (no fail-closed) | new |
| `settings:ENV-P4-002` | ENV-P4-002 | `src/backend/core/config/services/cache.py:333-339` | `keydb_active_replica: bool = Field(default=True)` (no fail-closed) | new |
| `settings:ENV-P4-003` | ENV-P4-003 | `src/backend/core/config/services/storage.py:16-22` | `FileStorageSettings.enabled: bool = Field(default=True)` (no fail-closed) | new |

---

## 4. Приоритизация (P0 → P4)

### 4.1 P0 (data-loss / security / race / fail-open) — **Sprint-блокеры**

Подмножества, которые **должны быть закрыты до прод-промоушена** в порядке приоритета:

**Tier 1A — критичные fail-open с потенциалом компрометации** (открывают bypass authz/tenant/RCE):

1. `security:SECURITY-P0-001` — SAML impersonation через cookie (одна строчка fix в `_verify_saml`)
2. `security:SECURITY-P0-002` — per-workflow SQL policy silently dropped (расширить framework signature)
3. `api:DOMAIN-P0-002` — admin_cron RCE через `importlib.import_module` без whitelist (whitelist в `admin_cron.py:86-94`)
4. `dsl:DOMAIN-P0-002` — ScriptRunner RCE (capability + language whitelist + env=None)
5. `dsl:DOMAIN-P0-003` — PickleDataFormat RCE в DSL marshal surface (удалить или подписать)
6. `services:SERV-P0-002` — AdminService fail-OPEN при gateway=None (raise вместо return)
7. `business-logic:BL-P0-001` + `BL-P0-002` — OSINT fail-OPEN (raise domain exception)

**Tier 1B — data-loss через silent fail** (PII остаётся / данные теряются / multi-tenant breach):

1. `security:SECURITY-P0-003` — `xml.etree` без defusedxml в SAML dev-mode (drop-in `defusedxml.ElementTree`)
2. `services:SERV-P0-001` + `business-logic:BL-P1-002` — **TenantFacade TypeError** (T-08 RESIDUAL + MUTATED) — критично: каждое `with_tenant(...)` падает
3. `entrypoints:ENTRY-P0-001` + `ENTRY-P0-002` — MQ consumer без DLQ (добавить `dlq_writer` + nack)
4. `dsl:DOMAIN-P0-004` — PII erasure silent fail-OPEN (`exchange.fail` вместо warning)
5. `rag:DOMAIN-P0-002` — PII fail-OPEN on ingest (quarantine при sanitizer failure)
6. `agents:AGENTS-P0-001` — `get_ai_agent_service()` raises `NotImplementedError` (apply `@app_state_singleton`)
7. `agents:AGENTS-P0-002` + `AGENTS-P0-003` — `_resolve_tokenizer`/`_resolve_runtime` always None (DI-resolution pattern)
8. `agents:AGENTS-P0-004` — LangGraphAgentProcessor bypass BaseAIProcessor template (override `_run` not `process`)
9. `agents:AGENTS-P0-005` — AgentMemoryService no `tenant_id` (закрыть 2 XFAIL DEFER-1)
10. `business-logic:BL-P1-001` — orders_dsl `.then()` AttributeError (заменить на `.activity()`)

**Tier 1C — test failures с production-impact**:

1. `infrastructure:INFRA-P0-001` — embedding cache test naming drift (rename или update test)
2. `infrastructure:INFRA-P0-002` — 9 outbox-stub arity failures (multi-instance safety untested)
3. `infrastructure:INFRA-P0-003` — CDC doc-test sync (decide docs vs tests)
4. `api:DOMAIN-P0-003` — generator/setup.py broken import (`git rm` — production dead code)
5. `rag:DOMAIN-P0-001` — multimodal RAG E2E 2 FAIL (trace `MultimodalRAGService.search`)
6. `rag:DOMAIN-P0-003` — RagCachePrewarmer phantom runtime (mark experimental или wire к lifespan)
7. `workflow:DOMAIN-WF-P0-001` — 4 processors без `@processor` (low effort fix)
8. `workflow:DOMAIN-WF-P0-002` — TemporalWorkerPool никогда не instantiated (HIGH effort, HIGH risk — требует Typer CLI + lifecycle)
9. `workflow:DOMAIN-WF-P0-003` — cancel_workflow fail-OPEN + layer violation (low effort fix)
10. `workflow:DOMAIN-WF-P0-004` — worker-handlers unreached (следствие P0-002)
11. `api:DOMAIN-P0-001` — HITL endpoints без permission/tenant (router-level guard + tenant_id filter)

### 4.2 P1 (architecture / layers / fail-silent guards) — Sprint-критичные

Большинство P1 — это **guard rails, которые не работают, но при этом не падают** (silent fail). Без них P0-fix'ы теряют аудит-trail. Группируются по доменам:

1. **Security/Authz**: `SECURITY-P1-001` (gateway adapter dead path), `SECURITY-P1-002` (sync `_casbin_check`/`_opa_check` hasattr dead path), `SERV-P1-003` (admin `_get_authz` swallows all), `SERV-P1-004` (audit outcome inconsistency).
2. **Layer boundaries**: `api:DOMAIN-P1-002` (admin_nats importlib), `dsl:DOMAIN-P1-001` (CDCProcessor dsl→infra), `dsl:DOMAIN-P1-005` (web.py dsl→services), `services:SERV-P1-002` (reverse-layer shims services→extensions).
3. **Test/operations drift**: `entrypoints:ENTRY-P1-002` (6 filewatcher test failures post-T-W1-05), `workflow:DOMAIN-WF-P1-001` (parallel workflow spec paradigms).
4. **Tenant isolation**: `entrypoints:ENTRY-P1-001` (SSE principal missing), `business-logic:BL-P1-003` (validate_inn None), `api:DOMAIN-P1-006` (info disclosure на 6 endpoints), `agents:AGENTS-P0-005` (cross-ref).
5. **Operational**: `entrypoints:ENTRY-P1-003/004` (webhook auth gap), `api:DOMAIN-P1-003/004` (admin_actions/admin_plugins mock-fallback fail-OPEN), `settings:ENV-P1-001..005` (config_audit path, Granian dup, Redis default broken, compose limits, env-var inconsistency), `dependencies:DOMAIN-P1-001..004` (CI allowlist drift + stale flag), `api:DOMAIN-P1-001/005` (mobile dead code + setup dead code).
6. **Agent_dsl**: `agents:AGENTS-P1-001/002` (16/17 processors не зарегистрированы, BindSkill orphaned).

### 4.3 P2 — cleanup (dead code / stubs / observability gaps)

Большинство P2 — это либо legitimate pattern (ABC NotImplementedError), либо косметика. Приоритет для Phase 3 cleanup sprint:

1. **Cross-domain dead-code sweep**: `infrastructure:INFRA-P2-002` (RouterLike → Protocol), `workflow:DOMAIN-WF-P2-001/002/003/004` (re-exports, replay no-op, over-broad except, dead workers), `agents:AGENTS-P2-001/002/003/004` (unreachable code, orphaned hot_reload, misleading docstrings, OrchestratorEngine dead), `services:SERV-P2-001..007` (admin `_audit_cb` dead, scheduled_reports over-broad except, observability DEBUG-swallows), `dependencies:DOMAIN-P2-001/002` (dead sphinx ~400 LOC + phantom-version dep), `settings:ENV-P2-001/002/003` (hardcoded default, layer violation в cache.py, 12+ Settings не агрегированы), `api:DOMAIN-P2-001` (mobile dead code), `business-logic:BL-P2-001/002/004` (SagaDeclaration dead, invalid test INN, silent ES failures).
2. **DSL/PII hardening (low priority)**: `dsl:DOMAIN-P2-002/003/004` (deprecation guard thread-safety, JDBC SQL whitelist, feature-flag boilerplate), `dsl:DOMAIN-P1-003/004` (metric silent + PII scope edge case).
3. **RAG cleanup**: `rag:DOMAIN-P2-001..005` (AugmentMixin malformed body, duplicate imports, dead RAGSearchProcessor, unused logger, bytes/str lookup).

### 4.4 P3 — library replacement (non-blocking)

Все P3 — candidates для замены кастомных реализаций на зрелые библиотеки (или наоборот, обоснованный отказ). Большинство либо обосновано (Ponytail-mode одобряет), либо low-priority:

1. **tenacity adoption gap**: `infrastructure:INFRA-P3-001/002` (обоснованно НЕ заменять; оставить), `rag:DOMAIN-P3-001` (резолютно RESIDUAL), `business-logic:BL-P3-001/002` (broad except — minor).
2. **Pydantic vs dataclass**: `agents:AGENTS-P3-001` (MemoryScope dual).
3. **Web/IO/Storage consolidation**: `services:SERV-P3-002/003/004` (exporters, JMESPath, re-export modules), `entrypoints:ENTRY-P3-001/002` (webhook registry dedup, private `_deserialize_request`).
4. **Auth consolidation**: `security:SECURITY-P3-001/002` (JWT через `JwtBackend`, Basic через `HTTPBasic`), `api:DOMAIN-P3-002` (APIKey middleware dedup).
5. **API registry replacement**: `api:DOMAIN-P3-001` (admin_cron callable registry).
6. **Statistics**: `infrastructure:INFRA-P3-003` (`statistics.quantiles` candidate; оставить если hdrh не убирают).
7. **Workflow custom code**: `workflow:DOMAIN-WF-P3-001/002/003/004` (launcher, payload converter, retry re-export, json → orjson).
8. **DSL/RAG cleanup**: `dsl:DOMAIN-P3-001/002/003` (pass-stub logging, ET→defusedxml mirror, AI cache pass-stubs), `rag:DOMAIN-P3-002` (Redis state store replacement).
9. **Settings**: `settings:ENV-P3-001/002/003/004` (drift cleanup).
10. **Dependencies**: `dependencies:DOMAIN-P3-001/002/003` (cross-pin duplicates, _parse_pin bug, deptry dead).

### 4.5 P4 — organic features (defer)

22 P4 находки — органичные feature candidates, которые **не должны блокировать прод-промоушен**. Группировка по приоритету:

1. **Auth/Security enhancements**: `security:SECURITY-P4-001/002` (OIDC support, SAML SLO).
2. **AI safety wire-up**: `agents:AGENTS-P4-001` (AgentSecurityFramework integration в extensions/credit_pipeline).
3. **RAG observability**: `rag:DOMAIN-P4-001/002` (Prometheus metrics, RecursiveCharacterTextSplitter).
4. **API enrichment**: `api:DOMAIN-P4-001` (OpenAPI `x-action-id`), `api:DOMAIN-P4-002` (tenacity for DSL pipeline).
5. **Workflow tooling**: `workflow:DOMAIN-WF-P4-001..005` (BPMN export, ramp via Temporal native, magic numbers, BPMN importer dead-code, cost-based cancellation).
6. **Settings defaults fail-closed**: `settings:ENV-P4-001/002/003` (DLQ cleanup, KeyDB active-replica, file storage).
7. **Infrastructure replay**: `infrastructure:INFRA-P4-001` (typed DLQ replay API).
8. **Services storage**: `services:SERV-P4-001/002/003` (DQ rule persistent storage, RPA retry policy, admin audit log).
9. **DSL coverage**: `dsl:DOMAIN-P4-001` (Camel ControlBus coverage).
10. **Entrypoints cleanup**: `entrypoints:ENTRY-P4-001` (subscribers.py vs invoker_subscribers.py).
11. **Business-logic demos**: `business-logic:BL-P4-001` (3 YAML workflows без loaders).

---

## 5. Явные противоречия между cycle-4 отчётами

> Phase 2 не разрешает противоречия чтением source. Все они помечены «нужна верификация разработчиком/архитектором».

### 5.1 T-08 TenantFacade kwargs — единый статус

**Согласованность**: ✅ Все источники указывают **RESIDUAL + MUTATED**:

- `services:SERV-P0-001` (Services domain): «TenantFacade.with_tenant is broken (T-08 fix is incorrect)»; `CapabilityTenant(tenant_id=..., principal_id=...)` — wrong kwargs; cycle-3 S193 fix introduced NEW bug.
- `business-logic:BL-P1-002` (Business Logic domain): «TenantFacade.with_tenant kwargs mismatch (RESIDUAL cycle-3 T-08)»; same path, same wrong kwargs.
- BASELINE.md: явно помечено как «RESIDUAL» с пометкой «T-08 TenantFacade kwargs fix».

**Контраст с cycle-3 планом**: «T-08 RESOLVED в HEAD 22e08a0d» (per BASELINE.md listing). Phase-1 фактически опровергает.

**Действие**: требуется re-fix в Phase 3 (одна строка: `CapabilityTenant(id=tenant_id, principal=principal_id)` + новый test без mock).

### 5.2 defusedxml drop-in (T-10) — частичный

**Конфликт 1**: cycle-3 plan заявлял «T-10 RESOLVED» (per BASELINE.md), но Phase-1 находит минимум **2 точки с stdlib `xml.etree.ElementTree`**:

- `security:SECURITY-P0-003` (Security domain): `core/auth/facade.py:490` — SAML dev-mode verify (XXE через billion-laughs).
- `dsl:DOMAIN-P0-001` (DSL domain): `dsl/engine/processors/eip/marshal/formats.py:91-140` — `XmlDataFormat.unmarshal` lazy-try fallback.
- Дополнительно `business-logic:10` отмечает T-10 как RESOLVED со ссылкой на `dsl/engine/processors/eip/marshal/formats.py:23,128-133` — то есть **Phase-1 внутри DSL-домена видит защиту, но тот же DSL-домен находит fallback**.

**Контрадикция**: DSL-домен сам себе противоречит: в strengths указано «XXE через defusedxml preferred», в findings — «fallback через stdlib при `defusedxml = None` (dev-light)».

**Действие**: требуется верификация архитектором — возможно ли полное удаление stdlib fallback (поскольку `defusedxml` уже в `uv.lock` и `bpmn_importer.py:55` hard-imports его)?

### 5.3 PickleDataFormat vs marshal RCE

**Контрадикция между доменами**:

- `dsl:DOMAIN-P0-003` (DSL): рекомендует «полностью удалить `PickleDataFormat` или перенести в `extensions/dev_tools/`».
- `security` и `infrastructure` не упоминают эту проблему (вне scope).

**Cross-check**: `security:SECURITY-P0-001..003` связаны с SAML/agent_security, не с marshal. Нет прямого конфликта, но DSL-only находка может быть blind spot для security-домена.

**Действие**: требуется верификация архитектором безопасности — `PickleDataFormat` действительно доступен из DSL production route?

### 5.4 PII fail-OPEN — разные модули, одинаковый паттерн

**Cross-domain pattern**:

- `dsl:DOMAIN-P0-004` (DSL): `pii_erase.py:139-228` — sanitize exception silently swallowed; PII остаётся.
- `rag:DOMAIN-P0-002` (RAG): `rag_ingest_service.py:224-226` — `except Exception → return content_text`; raw PII в vector store.
- `security:SECURITY-P0-002` (Security): `agent_security/facade.py:121-133` — `validate_sql` policy_override silently dropped (другой аспект PII/policy).

Все три — fail-OPEN на PII-критичных путях. **Не противоречие, а конвергенция**: разные домены независимо находят один и тот же anti-pattern.

**Действие**: единый Phase-3 fix — centralize PII fail-CLOSED contract (`pii.fail_closed = True` global flag + AuditEvent при violation).

### 5.5 DLQ wiring inconsistency (B-17 RESOLVED vs MQ RESIDUAL)

**Контрадикция между доменами** (только apparent, на самом деле разные subsystems):

- `infrastructure:INFRA-P0-002` отмечает B-17 CDC DLQ fix как RESOLVED (verified 13/13 cycle-37 guard tests).
- `entrypoints:ENTRY-P0-001/002` отмечают MQ (Redis Streams + RabbitMQ via FastStream) DLQ как RESIDUAL.

**Это не противоречие**, а констатация что:
- CDC subsystem (`src/backend/infrastructure/clients/external/cdc/`) — DLQ production-grade.
- MQ subsystem (`src/backend/entrypoints/stream/`) — DLQ отсутствует.

**Действие**: Phase 3 — DI provider `dlq_writer` для `stream_client` + `nack(requeue=False)`.

### 5.6 HITL auth — multiple sources

**Конвергенция**:

- `api:DOMAIN-P0-001` (API): HITL endpoints без router-level guard + cross-tenant via `tenant_id=None`.
- `entrypoints:ENTRY-P1-001` (Entrypoints): SSE principal не пробрасывается в `dispatch_action_or_dsl` (= 8 xfailed).
- Оба ссылаются на cycle-1 T-1.2 / cycle-2 T-W1-07.

**Не конфликт**, а взаимодополняющие находки. Phase 3 fix требует coordinated work между API и Entrypoints.

### 5.7 Temporal Worker lifecycle (workflow) vs outbox worker (infrastructure)

**Потенциальный конфликт**:

- `workflow:DOMAIN-WF-P0-002` отмечает что `TemporalWorkerPool` НЕ instantiated.
- `infrastructure` отмечает Outbox dispatcher (`_dispatch_one`) custom retry без tenacity (P3-001 — обоснованно).

**Не противоречие**, но указывает что workflow-домен имеет «большую дыру» (Temporal не работает), а infrastructure-домен уже нашёл замену (pg-runner fallback для dev_light, обоснованно).

**Действие**: Phase 3 ADR-level decision — оставлять ли только Temporal, или dual Temporal+pg-runner (см. `workflow:DOMAIN-WF-P1-001`).

### 5.8 credit_pipeline_v2 default inconsistency

**Конфликт между тестами** (cross-ref):

- `business-logic:BL-P2-003` (Business Logic): description говорит «default-OFF», `default=True` — `test_credit_pipeline_v2_flag.py:15-17` expects default-OFF (FAILED).
- `business-logic:BL-P2-003` (тот же домен): `tests/unit/core/config/test_features_plugins.py:17-18` expects default-ON.
- `services:03` (Services) НЕ перепроверял.

**Контрадикция внутри test suite**, не между отчётами. Требует coordination test + config fix.

### 5.9 Security `cycle-1 validate_sql drop` vs Phase-1 finding

**Конвергенция**:
- `security:SECURITY-P0-002` находит «Per-workflow SQL policy silently dropped» как NEW.
- Cycle-1 carry-over (`validate_sql drop`) — RESIDUAL.

**Не конфликт**, но указывает что cycle-1 RESIDUAL был полностью независимо переоткрыт в Phase-1 как P0.

### 5.10 B-17 fix location vs workflow Temporal lifecycle

**Потенциальный конфликт**:

- `infrastructure:01` подтверждает B-17 (CDC DLQ) RESOLVED.
- `workflow:07` находит 4 P0 о «Temporal-path не работает».
- Это не конфликт, но требует clarification: B-17 fix касался **только CDC DLQ**, не Temporal Workflow Worker. CDC ≠ Temporal Workflow — это разные subsystems (CDC = change data capture, Temporal = workflow orchestrator).

**Действие**: Phase 3 ADR — что именно считается «Temporal-path» и какие компоненты в нём участвуют.

---

## 6. Кандидатный минимальный набор задач Фазы 3

> Сгруппировано по принципу «атомарный fix = один PR». Зависимости и потенциально независимые workstreams выделены явно. **Phase 3 architect должен спроектировать diff** — Phase 2 не делает этого за него.

### 6.1 Workstream A: «Tenant isolation T-08 re-fix» (CRITICAL, 1 PR, 1 dev-day)

**Scope**: `src/backend/services/tenancy/facade.py:116-119` + integration test.

**Зависит от**: ничего.

**Содержит**:
- `services:SERV-P0-001` + `business-logic:BL-P1-002` (один и тот же bug).
- Re-fix: `CapabilityTenant(id=tenant_id, principal=principal_id)`.
- Add unit test `test_with_tenant_accepts_principal_id` без mock на `set_tenant`.

**Effort**: XS (1 строка + 1 тест).

**Critical-path**: да, без этого каждый multi-tenant scoped context = TypeError.

### 6.2 Workstream B: «PII fail-CLOSED contract» (1-2 PR, 2-3 dev-days)

**Scope**: PII-критичные пути в DSL + RAG + Security.

**Зависит от**: Workstream A (для unit-тестов в multi-tenant setup).

**Содержит**:
- `dsl:DOMAIN-P0-004` (PII erasure silent fail-OPEN).
- `rag:DOMAIN-P0-002` (PII fail-OPEN on ingest).
- `security:SECURITY-P0-002` (per-workflow SQL policy silently dropped).
- Optional: `business-logic:BL-P1-003` (validate_inn None guard).

**Усилия**: добавить `pii.fail_closed = True` global flag + `AuditEvent` при violation; quarantine queue для RAG ingest.

**Effort**: M (multiple modules, coordinated test).

### 6.3 Workstream C: «SAML + authn bypass fix» (1-2 PR, 3-5 dev-days)

**Scope**: SAML impersonation + admin fail-OPEN + capability hardcoded None.

**Содержит**:
- `security:SECURITY-P0-001` (SAML session trust — high impact).
- `services:SERV-P0-002` (AdminService._authorize fail-OPEN).
- `security:SECURITY-P1-001` (AIGatewayProductionWiringError dead path).
- `security:SECURITY-P0-003` (defusedxml drop-in в SAML).

**Effort**: M-L (multiple security-critical paths).

### 6.4 Workstream D: «RCE fixes» (1-2 PR, 2-4 dev-days)

**Scope**: ScriptRunner, PickleDataFormat, admin_cron RCE, mobile BFF.

**Содержит**:
- `dsl:DOMAIN-P0-002` (ScriptRunner RCE).
- `dsl:DOMAIN-P0-003` (PickleDataFormat RCE).
- `api:DOMAIN-P0-002` (admin_cron RCE — highest priority admin-side).
- `api:DOMAIN-P1-005` (mobile BFF dead code — `git rm`).

**Effort**: M (DSL deep changes + API whitelist).

### 6.5 Workstream E: «Temporal Worker lifecycle» (1 PR, HIGH effort, HIGH risk, 1 sprint)

**Scope**: Workflow-домен, Temporal-path activation.

**Содержит**:
- `workflow:DOMAIN-WF-P0-002` (TemporalWorkerPool instantiated + Typer CLI).
- `workflow:DOMAIN-WF-P0-001` (4 missing `@processor` decorators — low effort, separate commit).
- `workflow:DOMAIN-WF-P0-003` (cancel_workflow fail-OPEN + layer violation — low effort).
- `workflow:DOMAIN-WF-P0-004` (worker-handlers unreached — следствие P0-002).
- `workflow:DOMAIN-WF-P1-001/002/003` (parallel paradigms, cancel phantom-success, AI cold-start — dependent decisions).

**Effort**: HIGH (требует integration testing с реальным Temporal-кластером, requires `uv sync --extra workflow`).

**Зависит от**: ADR-level decision (YAGNI vs Adapter).

### 6.6 Workstream F: «MQ DLQ + webhook HMAC hardening» (1-2 PR, 2-3 dev-days)

**Scope**: MQ + webhook + DLQ wiring.

**Содержит**:
- `entrypoints:ENTRY-P0-001` + `ENTRY-P0-002` (MQ consumer без DLQ).
- `entrypoints:ENTRY-P1-003/004` (webhook auth gap + HMAC fail-OPEN).
- `services:SERV-P0-003` (WebhookRelay DLQ silent-loss).
- `entrypoints:ENTRY-P2-001/002/003` (broad except cleanup — low priority).
- `entrypoints:ENTRY-P3-001/002` (webhook registry consolidation).

**Effort**: M (multiple integrations + tests).

### 6.7 Workstream G: «HITL + cross-tenant permissions» (1-2 PR, 2-3 dev-days)

**Scope**: HITL authz + tenant enforcement.

**Содержит**:
- `api:DOMAIN-P0-001` (HITL endpoints без permission/tenant).
- `entrypoints:ENTRY-P1-001` (SSE principal не пробрасывается).
- `api:DOMAIN-P1-006` (6 endpoints без role-guard).
- `agents:AGENTS-P0-005` (AgentMemoryService no tenant_id — закрыть 2 XFAIL).

**Effort**: M (router-level guards + tenant context propagation).

### 6.8 Workstream H: «Agents DSL registration + PII/guards fixes» (1-2 PR, 2-3 dev-days)

**Scope**: agent_dsl processors + PII/guards runtime.

**Содержит**:
- `agents:AGENTS-P0-001` (`get_ai_agent_service()` raises NotImplementedError — apply @app_state_singleton).
- `agents:AGENTS-P0-002` (PIIUnmaskProcessor DI).
- `agents:AGENTS-P0-003` (GuardrailsApplyProcessor DI).
- `agents:AGENTS-P0-004` (LangGraphAgentProcessor override `_run` not `process`).
- `agents:AGENTS-P1-001/002` (16/17 agent_dsl processors + BindSkill — register + feature_flag).

**Effort**: M (multiple files, capability/feature_flag registration).

### 6.9 Workstream I: «OSINT fail-OPEN + orders_dsl `.then()`» (1 PR, 1 dev-day)

**Scope**: extensions business-logic critical-path.

**Содержит**:
- `business-logic:BL-P0-001` + `BL-P0-002` (OSINT fail-OPEN).
- `business-logic:BL-P1-001` (orders_dsl `.then()` AttributeError — runtime crash).

**Effort**: S (3 critical bugs, all small fixes).

### 6.10 Workstream J: «Tests + infrastructure test drift cleanup» (1-2 PR, 1-2 dev-days)

**Scope**: Test failures / drift.

**Содержит**:
- `infrastructure:INFRA-P0-001` (embedding cache test naming drift).
- `infrastructure:INFRA-P0-002` (9 outbox-stub arity failures).
- `infrastructure:INFRA-P0-003` (CDC doc-test sync).
- `infrastructure:T-06` (test-infra conftest — capability gate).
- `api:DOMAIN-P0-003` (generator/setup.py `git rm` — dead code).
- `entrypoints:ENTRY-P1-002` (6 filewatcher test failures post-T-W1-05).
- `business-logic:BL-P2-002` (invalid 12-digit INN test data).

**Effort**: S-M (mostly mechanical fixes).

### 6.11 Workstream K: «Settings + dependencies cleanup» (1 PR, 1-2 dev-days)

**Scope**: config_audit + Granian + Redis + CI drift.

**Содержит**:
- `settings:ENV-P1-001` (config_audit stale path — 3 lines).
- `settings:ENV-P1-002` (duplicate Granian surface — architectural decision).
- `settings:ENV-P1-003` (Redis cluster_mode default broken — 2 lines).
- `settings:ENV-P1-004` (compose без CPU/memory limits — 7 файлов).
- `settings:ENV-P1-005` (3 env-vars — refactor all callsites).
- `settings:ENV-P2-001/002/003` (cleanup + Settings aggregator).
- `dependencies:DOMAIN-P1-001/002/003/004` (CI sync + stale flag).
- `dependencies:DOMAIN-P2-001` (dead sphinx ~400 LOC).
- `dependencies:DOMAIN-P2-002` (phantom-version presidio-ru-recognizers).
- `business-logic:BL-P2-003` (credit_pipeline_v2 default).

**Effort**: M (cross-cutting).

### 6.12 Workstream L: «P2 cleanup batch» (1-2 PR, 2-3 dev-days, defer)

**Scope**: All non-blocking P2.

**Содержит**: 42 P2 находки (см. §3.3 и §4.3).

**Effort**: M (bulk cleanup, mostly mechanical).

**Зависит от**: не критично; можно делать после A-K.

### 6.13 Workstream M: «P3 library replacement batch» (defer to cycle 5+)

**Scope**: 32 P3 находки (см. §3.4 и §4.4).

**Effort**: L (большинство — library migration; требует testing).

**Зависит от**: только после стабилизации P0+P1+P2.

### 6.14 Workstream N: «P4 organic features» (defer to cycle 6+)

**Scope**: 22 P4 находки (см. §3.5 и §4.5).

**Effort**: L (новый функционал; не блокирует прод-промоушен).

### 6.15 Граф зависимостей между workstreams

```
A (T-08 re-fix) ── independent, critical-path
                  └─> tests in B, C могут использовать multi-tenant setup

B (PII fail-CLOSED) ── depends-on A (для тестов)
                     └─> feeds into C (audit events)

C (SAML + authn) ── independent от A, B
                  └─> shares patterns with D

D (RCE fixes) ── independent от A, B, C
                └─> DSL marshal changes могут зацепить B (PII surface)

E (Temporal Worker) ── HIGH RISK, depends-on architecture decision
                     └─> может поглотить F (DLQ wiring) для cancel-handling

F (MQ DLQ + webhook) ── depends-on C (capability contract)
                       └─> feeds into E (cancel_workflow fix)

G (HITL + cross-tenant) ── independent от A-F
                         └─> может пересекаться с C (AuthRequiredMiddleware)

H (Agents DSL) ── independent от A-G
                  └─> feeds into G (AgentMemory tenant_id)

I (OSINT + orders_dsl) ── independent от A-H
                          └─> BL-P0-001/002 + BL-P1-001 fix

J (Tests cleanup) ── parallel к любому workstream (test fixes)
                    └─> содержит T-06 capability-gate conftest

K (Settings + deps cleanup) ── independent от A-J
                              └─> содержит cycle-3 residual P1-001/002 cleanup

L (P2 cleanup) ── after A-K (bulk cleanup)
M (P3 library replacement) ── cycle 5+ (defer)
N (P4 organic features) ── cycle 6+ (defer)
```

### 6.16 Потенциально независимые workstreams (можно делать параллельно)

- **A + I** — разные модули, разные домены, оба critical.
- **D + G** — DSL vs API, разные layer.
- **H + K** — services vs config.
- **J** — можно делать параллельно с чем угодно (test fixes инкрементальны).

**Рекомендуемая последовательность для Phase 3**:

1. Sprint 1: A (T-08 re-fix), I (OSINT + orders_dsl), J (tests) — quick wins.
2. Sprint 2: B (PII fail-CLOSED), C (SAML + authn), G (HITL) — security hardening.
3. Sprint 3: D (RCE fixes), F (MQ DLQ + webhook), H (Agents DSL) — поверхность.
4. Sprint 4: K (Settings + deps cleanup), L (P2 cleanup) — house keeping.
5. Cycle 5+: E (Temporal Worker — HIGH risk, может требовать отдельного ADR), M (P3 libraries), N (P4 organic).

---

## 7. Library replacement table

> Колонки: library candidate → cited custom code (path:line) → installed status (verified in cycle-4 Phase-1) → expected LOC reduction → license/maintenance evidence.

### 7.1 P0-level (security-critical) library replacement candidates

| Library | Cited custom code (Phase-1 evidence) | Installed status | Expected LOC reduction | License / Maintenance evidence |
|---|---|---|---|---|
| **defusedxml.ElementTree** (P0 drop-in) | `core/auth/facade.py:488-493` (SECURITY-P0-003); `dsl/engine/processors/eip/marshal/formats.py:91-140` (DOMAIN-P0-001) | ✅ installed (per `bpmn_importer.py:55` hard-import, `pyproject.toml:165-167` comment) | -10 LOC (delete try/except fallback); +5 LOC (drop-in wrapper) | Apache 2.0, defusedxml maintainers active (verified in `pyproject.toml`); pip-audit allowlist clear; **NOT verified**: full maintenance history (network blocked) |
| **joserfc** (JWT consolidation) | `core/auth/auth_selector.py:178-211` (`_verify_express_jwt`) | ✅ installed (per `core/auth/jwt_backend.py` use; pyproject.toml dep) | -45 LOC (delete custom HS256 + claim validation) | Apache 2.0, joserfc maintainers active; **NOT verified**: full maintenance history |
| **HTTPBasic** (FastAPI stdlib) | `core/auth/auth_selector.py:97-108` (`_verify_basic`) | ✅ stdlib (FastAPI dep) | -12 LOC (delete custom base64 decode) | BSD, FastAPI maintainers active |
| **tenacity** (for DSL/RAG) | `outbox/dispatcher.py:276-310` (P3-001 — обоснованно НЕ заменять); `services/ai/rag_service/{ingest,search,augment,collection}_mixin.py` (DOMAIN-P3-001) | ✅ installed (per `agents_pydantic/base.py:226`, `pyproject.toml:74`) | -30 LOC (delete manual retry в RAG services) + 1-line decorator | Apache 2.0, tenacity maintainers active |

### 7.2 P3 library replacement candidates

| Library | Cited custom code | Installed status | Expected LOC reduction | License / Maintenance evidence |
|---|---|---|---|---|
| **`packaging.version` + `pip` resolver** | `dsl/workflow/launcher.py:1-208` (`WorkflowLauncher` + `SpecifierSet`) | ✅ installed (`packaging>=24.0` per pyproject) | -100 LOC (delete semver resolution) | BSD, PyPA maintainers active |
| **`temporalio.converter.DefaultPayloadConverter`** | `dsl/workflow/compiler/step_compilers.py:67-68` + `infrastructure/workflow/temporal_backend.py:42-101` (`canonical_json_bytes`) | ⚠️ opt-in (`uv sync --extra workflow`) | -60 LOC | Apache 2.0, Temporal maintainers active |
| **`orjson`** (JSON serialization) | `workflow/best_practices/claim_check.py:102-104` (`json.dumps(payload, ensure_ascii=False, default=str)`) | ✅ installed (per codebase use) | -3 LOC (1-line replace) | Apache 2.0, maintainers active; **NOT verified**: full maintenance history |
| **`statistics.quantiles`** (stdlib) | `infrastructure/application/slo_tracker.py:30-67` (`_FallbackStats`) | ✅ stdlib (Python 3.14) | -15 LOC | PSF, stdlib (always maintained) |
| **`pyarrow` + `tabulate`** (exporters) | `services/io/export_service.py:39-310` (5 hand-rolled exporters) | ⚠️ opt-in (`uv sync --extra rag` likely) | -200 LOC (consolidate exporters) | Apache 2.0, maintainers active |
| **`Redis JSON` (`redis.asyncio.Redis.json()`)** | `services/ai/rag_ingest_store.py:139-268` (custom HASH+ZSET) | ✅ installed (Redis Stack 7.4+ requirement) | -80 LOC | BSD, Redis maintainers active |
| **`langchain.text_splitter.RecursiveCharacterTextSplitter`** | `services/ai/rag_service/ingest_mixin.py:35-48` (naive chunker) | ✅ installed (per pyproject) | -10 LOC | MIT, langchain maintainers active |
| **`prometheus_client`** (RAG metrics) | `services/ai/rag_query_stats.py:43-64` (no metrics export) | ✅ installed (per codebase use) | +20 LOC (counter) + 5 LOC test | Apache 2.0, maintainers active |

### 7.3 P3 candidates, обоснованно НЕ заменять

| Custom code | Обоснование (Phase-1 evidence) |
|---|---|
| `outbox/dispatcher.py:276-310` (`_dispatch_one` custom retry) | Tenacity `AsyncRetrying` плохо работает с graceful shutdown через `asyncio.wait_for(self._stopping.wait(), timeout=…)` (per-attempt DB state + transactional ack). Ponytail-mode одобряет. |
| `infrastructure/resilience/reconnection.py:91-122` (custom reconnect) | Tenacity `retry_forever` менее explicit, чем `while True` + explicit backoff. |
| `infrastructure/application/slo_tracker.py:30-67` (`_FallbackStats`) | HdrHistogram preferred path; fallback срабатывает только если hdrh не установлен. Custom OK. |

### 7.4 License / Maintenance summary (P0+P3 candidates)

| Library | License | Maintenance status (per Phase-1 evidence) |
|---|---|---|
| defusedxml | Apache-2.0 | **NOT verified** (network blocked) |
| joserfc | MIT | **NOT verified** (network blocked) |
| FastAPI | BSD | active (used in codebase) |
| tenacity | Apache-2.0 | **NOT verified** |
| packaging | BSD | PyPA active |
| temporalio | Apache-2.0 | **NOT verified** |
| orjson | Apache-2.0 | **NOT verified** |
| pyarrow | Apache-2.0 | **NOT verified** |
| tabulate | MIT | **NOT verified** |
| langchain | MIT | **NOT verified** |
| prometheus_client | Apache-2.0 | **NOT verified** |
| redis (asyncio) | BSD | active |

**Замечание**: Phase-1 инфра-домен не выполнял network-pypi checks (timeout); dependency-домен тоже. Точный статус maintenance — **нужна верификация разработчиком/архитектором** через PyPI перед коммитом.

---

## 8. Organic feature table

> Колонки: benefit → architecture fit → evidence (Phase-1) → defer/plan recommendation.

| Organic feature (Phase-1 P4 ID) | Benefit | Architecture fit | Phase-1 evidence | Recommendation |
|---|---|---|---|---|
| **`AuthMethod.OIDC`** (SECURITY-P4-001) | Modern enterprise SSO (Keycloak/OIDC/Okta); security-debt closing | Camel-style DSL auth-method (extension); `joserfc`/`python-jose` already installed | `sso_types.py:20` comment «S126+ carryover»; `AuthMethod` enum (8 членов) without OIDC | **DEFER** to cycle 6 (organic addition, not blocking) |
| **SAML SLO** (SECURITY-P4-002) | Per-IdP revocation hook for SAML sessions | Extension to `SecurityFacade.blacklist_saml_session`; pattern parallel to `RedisJwtBlacklist` | `services/security/facade.py:265-289` pattern; only JWT blacklist exists | **DEFER** to cycle 5+ (depends on SAML session validation fix — Workstream C) |
| **OpenAPI `x-action-id`** (DOMAIN-P4-001) | Developer experience for ActionRouterBuilder; Streamlit Developer Portal | FastAPI customizer; existing `add_api_route` already generates OpenAPI | `specs.py:98` has `action_id`; not exported to OpenAPI | **DEFER** to cycle 5+ (small LoC ~20) |
| **Tenacity for DSL pipeline retry** (DOMAIN-P4-002) | Replaces ad-hoc retry; consistency with services/agents | DSL processor template (`BaseProcessor.handle_processor_error`) | T-W3-01 cycle-2 deferred; `agent_run.py:188` already uses tenacity | **DEFER** to cycle 5+ (post-MVP) |
| **`Camel ControlBus`** (DOMAIN-P4-001) | Camel/Airflow EIP coverage gap | DSL processor; `wire_tap.py` exists, `idempotency.py` exists | DSL-домен отмечает gap | **DEFER** (YAGNI — Ponytail-mode одобряет «не делать без бизнес-обоснования») |
| **BPMN XML export** (DOMAIN-WF-P4-001) | Compliance visualization (BPMN round-trip); Camel-style DSL operator | DSL workflow compiler; `visualize.py → to_graphviz/to_mermaid` partially closes | `bpmn_importer.py` + `dryrun.py` exist; reverse path missing | **DEFER** to Sprint 37+ (organic fit, not YAGNI) |
| **`should_route_to_this_version` ramp** (DOMAIN-WF-P4-002) | Native Temporal ramp support | `infrastructure/workflow/versioning/worker_versioning.py` | Custom vs Temporal native `ramp_percentage` | **DEFER** (post-MVP; YAGNI for now) |
| **Magic numbers в step-compilers** (DOMAIN-WF-P4-003) | Code clarity (`_REFLECT_ACTIVITY_TIMEOUT_S = 60`) | DSL workflow compiler; minor refactor | Multiple magic literals | **DEFER** (cosmetic) |
| **BPMN importer / visualize default-OFF cleanup** (DOMAIN-WF-P4-004) | Dead code removal (~1000 LOC) | DSL workflow | BPMN importer 535 LOC + visualize 460 LOC | **DEFER** (decision: delete or wire-up) |
| **Cost-based cancellation** (DOMAIN-WF-P4-005) | Camunda CostDecisions analog; `breach_action="cancel"` extension | DSL workflow `SlaPolicy` + `cost_estimator.py` | `breach_action ∈ {alert,cancel,none}` | **DEFER** to cycle 6+ (organic extension) |
| **AgentSecurityFramework wire-up** (AGENTS-P4-001) | Banking `banking_transaction_hook` activated in production | `extensions/credit_pipeline/routes/` + DSL agent_security_check | 667 LOC framework + 10/10 tests + 30/30 tests; no consumer | **DEFER** to cycle 5+ (high value for compliance, but no immediate blocker) |
| **RAG Prometheus metrics** (DOMAIN-P4-001) | Observability for `RagQueryStatsCollector` | `core/utils/metrics_registry.py` (already used by `hybrid_rag.py:30-39`) | `RagCachePrewarmer` exports counters via direct `prometheus_client` import | **DEFER** (organic addition) |
| **Langchain `RecursiveCharacterTextSplitter`** (DOMAIN-P4-002) | Better RAG retrieval quality (token-aware, sentence-boundary) | `services/ai/rag_service/ingest_mixin.py:35-48`; `langchain.text_splitter` already in deps | Current naive sliding-window chunker | **DEFER** (3-line replacement) |
| **DLQ replay API** (INFRA-P4-001) | EIP «Dead Letter Channel» completeness | `cdc_replay_dlq(scope, since)` DSL action | Failed events попадают в DLQ (B-02/B-17) but no replay | **DEFER** to cycle 5+ (post B-17 stabilization) |
| **Persistent DQ rules storage** (SERV-P4-001) | Camel-style configurator for per-tenant DQ profiles | `services/ops/data_quality/`; in-memory currently | Camel/Airflow pattern | **DEFER** to cycle 5+ |
| **Structured RPA retry policy** (SERV-P4-002) | Idempotent consumer with retry (Camel) | `core.resilience.retry` + tenacity | `rpa/*` ad-hoc `try/except` per method | **DEFER** (depends on Workstream H) |
| **`AdminService.get_audit_log` stub** (SERV-P4-003) | Real audit-log query | Backend storage TBD; `emit_admin_action` works | Stub returns `[]` | **DEFER** to cycle 5+ |
| **DSL-action `action_handler_registry` cleanup** (ENTRY-P4-001) | Document or delete legacy pathway | `entrypoints/stream/{subscribers.py,invoker_subscribers.py}` | Both import `stream_client` | **DEFER** (documentation only) |
| **3 YAML workflows loaders** (BL-P4-001) | Either wire-up or delete | `extensions/credit_pipeline/workflows/{multi_agent_supervisor,code_interpreter_loop,rag_augmented_saga}.workflow.yaml` | No runtime-loader; references only | **DEFER** (Ponytail: deletion over addition) |
| **DLQ cleanup opt-in default** (ENV-P4-001) | Fail-closed by default | `services/dlq.py:44-51` | `DLQCleanupSettings.enabled: bool = Field(default=True)` | **DEFER** (config policy decision) |
| **KeyDB active-replica opt-in** (ENV-P4-002) | Fail-closed by default | `services/cache.py:333-339` | `keydb_active_replica: bool = Field(default=True)` | **DEFER** (config policy decision) |
| **File storage opt-in** (ENV-P4-003) | Fail-closed by default | `services/storage.py:16-22` | `FileStorageSettings.enabled: bool = Field(default=True)` | **DEFER** (config policy decision) |

**Итог по organic features**: 22 P4 candidates. **Ни одна не блокирует прод-промоушен.** Все рекомендуются к defer (cycle 5+ или cycle 6+), за исключением:
- **`AuthMethod.OIDC`** (SECURITY-P4-001): органично, если Phase 3 закрывает SECURITY-P0-001 (SAML impersonation), можно сразу добавить OIDC.
- **Cost-based cancellation** (DOMAIN-WF-P4-005): органично для banking workflows — может войти в тот же sprint, что и `AgentSecurityFramework wire-up` (AGENTS-P4-001) для credit_pipeline.
- **3 YAML workflow loaders** (BL-P4-001): решение — **удалить** (Ponytail одобряет deletion over addition), не wire-up.

---

## 9. Итог: какие P0/P1 блокируют порог ≥80 для каждого домена

> Readiness ≥80 запрещена при наличии P0/P1 (per AGENTS.md). Для каждого домена перечислены **минимальные fix-наборы**, которые позволят домену достичь ≥80 (с учётом cap).

### 9.1 Infrastructure (текущий score 30, cap ≤79)

**Блокируют P0/P1** (для достижения ≥80):

- INFRA-P0-001 (embedding cache test naming drift) — **закрывает CI gate**.
- INFRA-P0-002 (9 outbox stub arity failures) — **доказывает multi-instance safety**.
- INFRA-P0-003 (CDC doc-test sync) — **закрывает 4 failures**.
- INFRA-P1-001 (duplicated asyncpg instrumentation) — **feature_flag contract**.

**Минимальный fix-набор**: 4 fixes (P0+P1 batch). После закрытия: raw ≈ 78, cap 79 → score ≥79 (если нет новых P0).

### 9.2 Security (текущий score 0, clamp)

**Блокируют P0**:

- SECURITY-P0-001 (SAML impersonation) — **критично**.
- SECURITY-P0-002 (per-workflow SQL policy silently dropped) — **критично**.
- SECURITY-P0-003 (xml.etree без defusedxml) — **критично**.

**Минимальный fix-набор**: 3 P0 (Workstream C) + P1-001/002 (Workstream C). После закрытия: raw ≈ 50, cap 79 → score ≥79.

### 9.3 Services (текущий score 0, clamp)

**Блокируют P0**:

- SERV-P0-001 (TenantFacade TypeError — T-08) — **критично** (cross-ref Workstream A).
- SERV-P0-002 (AdminService fail-OPEN) — **критично** (cross-ref Workstream C).
- SERV-P0-003 (WebhookRelay DLQ silent-loss) — **критично** (cross-ref Workstream F).
- SERV-P1-001/002/003/004 — **architecture + dead code + root cause + observability**.

**Минимальный fix-набор**: 3 P0 + 4 P1 (Workstreams A+C+F). После закрытия: raw ≈ 70, cap 79 → score ≥79.

### 9.4 Entrypoints (текущий score 57, cap ≤79)

**Блокируют P0**:

- ENTRY-P0-001 (MQ consumer без DLQ — `invoker_subscribers.py`) — **критично**.
- ENTRY-P0-002 (MQ consumer без DLQ — `subscribers.py`) — **критично**.
- ENTRY-P1-001 (SSE principal missing — 8 xfailed) — **close out**.

**Минимальный fix-набор**: 2 P0 + 1 P1 (Workstreams F+G). После закрытия: raw ≈ 60, cap 79 → score ≥79.

### 9.5 API (текущий score 60, cap ≤60)

**Блокируют P0**:

- DOMAIN-P0-001 (HITL cross-tenant bypass) — **критично** (cross-ref Workstream G).
- DOMAIN-P0-002 (admin_cron RCE) — **критично** (cross-ref Workstream D).
- DOMAIN-P0-003 (generator/setup.py broken import — `git rm`) — **dead code**.
- DOMAIN-P1-001..006 — **architecture + mock-fallback + dead code + info disclosure**.

**Минимальный fix-набор**: 3 P0 + 6 P1 (Workstreams D+G+J). После закрытия: raw ≈ 60, cap 60 → score ≥60 (cycle-3 baseline cap 60).

### 9.6 DSL (текущий score 0, clamp)

**Блокируют P0**:

- DOMAIN-P0-001 (XXE через stdlib-fallback) — **критично**.
- DOMAIN-P0-002 (ScriptRunner RCE) — **критично**.
- DOMAIN-P0-003 (PickleDataFormat RCE) — **критично**.
- DOMAIN-P0-004 (PII erasure silent fail-OPEN) — **критично** (cross-ref Workstream B).
- DOMAIN-P1-001..005 — **layer violations + silent fail-OPEN + observability**.

**Минимальный fix-набор**: 4 P0 + 5 P1 (Workstreams B+D). После закрытия: raw ≈ 70, cap 79 → score ≥79.

### 9.7 Workflow (текущий score 34, cap 79)

**Блокируют P0**:

- DOMAIN-WF-P0-001 (4 processors без `@processor`) — **low effort**.
- DOMAIN-WF-P0-002 (TemporalWorkerPool не instantiated) — **HIGH effort, HIGH risk**.
- DOMAIN-WF-P0-003 (cancel_workflow fail-OPEN + layer violation) — **low effort**.
- DOMAIN-WF-P0-004 (worker-handlers unreached) — **следствие P0-002**.
- DOMAIN-WF-P1-001/002/003 — **architecture + cancel phantom + AI cold-start**.

**Минимальный fix-набор для ≥79**: 4 P0 + 3 P1 (Workstream E — HIGH effort, 1 sprint). Без P0-002/P0-004 (Temporal wire-up) невозможно достичь ≥80.

**Альтернатива** (если Temporal wire-up deferred to cycle 5+): закрыть только P0-001 (low effort) + P0-003 (low effort), плюс P1-001/002 (architecture decisions); score поднимется до ~50, но **не ≥80**.

### 9.8 Agents (текущий score 46, cap 79)

**Блокируют P0**:

- AGENTS-P0-001 (`get_ai_agent_service` NotImplementedError) — **критично**.
- AGENTS-P0-002 (PIIUnmaskProcessor `_resolve_tokenizer`) — **критично** (cross-ref Workstream B).
- AGENTS-P0-003 (GuardrailsApplyProcessor `_resolve_runtime`) — **критично**.
- AGENTS-P0-004 (LangGraphAgentProcessor bypass template) — **критично**.
- AGENTS-P0-005 (AgentMemoryService no tenant_id) — **критично** (cross-ref Workstream G).
- AGENTS-P1-001/002 — **orphaned processor + 16/17 unregistered**.

**Минимальный fix-набор**: 5 P0 + 2 P1 (Workstreams H+G). После закрытия: raw ≈ 78, cap 79 → score ≥79.

### 9.9 RAG (текущий score 1, cap ≤60)

**Блокируют P0**:

- DOMAIN-P0-001 (multimodal RAG E2E 2 FAIL — T-4.1/T-W4-01) — **критично**.
- DOMAIN-P0-002 (PII fail-OPEN on ingest) — **критично** (cross-ref Workstream B).
- DOMAIN-P0-003 (RagCachePrewarmer phantom — T-W1-06) — **критично**.
- DOMAIN-P1-001 (citation score contract violation) — **architecture**.
- DOMAIN-P2-001..005 — **cleanup batch**.

**Минимальный fix-набор**: 3 P0 + 1 P1 + 5 P2 (Workstreams B+J+L). После закрытия: raw ≈ 60, cap 60 → score ≥60.

### 9.10 Business Logic (текущий score 30, cap 79)

**Блокируют P0/P1**:

- BL-P0-001 + BL-P0-002 (OSINT fail-OPEN) — **критично** (Workstream I).
- BL-P1-001 (orders_dsl `.then()` AttributeError) — **критично** (Workstream I).
- BL-P1-002 (TenantFacade kwargs — T-08 RESIDUAL) — **критично** (cross-ref Workstream A).
- BL-P1-003 (validate_inn None) — **low effort**.

**Минимальный fix-набор**: 2 P0 + 3 P1 (Workstreams A+I). После закрытия: raw ≈ 78, cap 79 → score ≥79.

### 9.11 Dependencies (текущий score 49, cap 79)

**Блокируют P1** (нет P0):

- DOMAIN-P1-001 (path mismatch — 1 line).
- DOMAIN-P1-002 (GH CI allowlist drift — 5 lines).
- DOMAIN-P1-003 (GitLab CI no gate wrapper — 5 lines).
- DOMAIN-P1-004 (stale `--ignore-vuln PYSEC-2026-87` — 1 line).

**Минимальный fix-набор**: 4 P1 (Workstream K, ~12 lines). После закрытия: raw ≈ 70, cap 79 → score ≥79.

### 9.12 Settings / Environment (текущий score 36, cap 79)

**Блокируют P1** (нет P0):

- ENV-P1-001 (config_audit stale path — 3 lines).
- ENV-P1-002 (duplicate Granian surface — architectural).
- ENV-P1-003 (Redis cluster_mode default broken — 2 lines).
- ENV-P1-004 (compose без CPU/memory limits — 7 файлов).
- ENV-P1-005 (3 env-vars — refactor all callsites).

**Минимальный fix-набор**: 5 P1 + 3 P2 + 4 P3 + 3 P4 (Workstream K). После закрытия: raw ≈ 60, cap 79 → score ≥79.

### 9.13 Сводка по доменам и зависимостям

| Домен | Достижимый ≥80 после закрытия | Workstream | Зависит от |
|---|---|---|---|
| Infrastructure | ✅ | J + частично K | — |
| Security | ✅ | B + C | — |
| Services | ✅ | A + C + F | A (T-08) |
| Entrypoints | ✅ | F + G | C (capability contract) |
| API | ⚠️ cap 60 (cycle-3 baseline) | D + G + J | — |
| DSL | ✅ | B + D | — |
| Workflow | ⚠️ только при Workstream E (HIGH effort) | E | ADR decision |
| Agents | ✅ | H + G | C (capability contract) |
| RAG | ⚠️ cap 60 | B + J + L | B |
| Business Logic | ✅ | A + I | A |
| Dependencies | ✅ | K | — |
| Settings | ✅ | K | — |

**Минимальный Phase-3 набор для достижения ≥80 в максимальном числе доменов**:

- Workstream **A** (T-08 re-fix) — критичный для Services + Business Logic.
- Workstream **B** (PII fail-CLOSED) — критичный для DSL + RAG + Security.
- Workstream **C** (SAML + authn) — критичный для Security + Services + Agents.
- Workstream **D** (RCE fixes) — критичный для DSL + API.
- Workstream **F** (MQ DLQ + webhook) — критичный для Entrypoints + Services.
- Workstream **G** (HITL + cross-tenant) — критичный для API + Entrypoints + Agents.
- Workstream **H** (Agents DSL) — критичный для Agents.
- Workstream **I** (OSINT + orders_dsl) — критичный для Business Logic.
- Workstream **J** (tests cleanup) — критичный для Infrastructure + API + RAG.
- Workstream **K** (Settings + deps) — критичный для Dependencies + Settings.

**Не достижимы ≥80 в Phase 3** (требуют cycle 5+):

- **Workflow**: требует Workstream E (Temporal Worker lifecycle, HIGH risk, HIGH effort).
- **API**: cap 60 per cycle-3 baseline (не ≥80, но ≥60 достижим).
- **RAG**: cap 60 (per RAG-домен формула).

---

## 10. Финальная сводка для parent agent

- **Доменов всего**: 12. **С P0/P1**: 12. **Готовых ≥80**: 0.
- **Findings**: 172 (P0:32, P1:44, P2:42, P3:32, P4:22).
- **8 правок cycle 1+2+3 в HEAD 22e08a0d**:
  - ✅ 5 чистых RESOLVED (T-1.4, T-3.1, T-W1-05, T-W1-08, T-02).
  - ⚠️ 2 RESOLVED + MUTATION (T-1.5 AIGatewayProductionWiringError dead path; T-W1-01 canonical path switch).
  - ⚠️ 1 RESOLVED + RESIDUAL (T-03 hardcoded default=30 в `granian_tuning.py:125`).
  - ❌ **1 КРИТИЧНЫЙ RESIDUAL + MUTATED (T-08 TenantFacade kwargs)** — фасад сломан; требует немедленного re-fix.
- **Cross-domain блокеры** (Phase 3 priority order):
  1. **T-08 TenantFacade** (Workstream A, 1 строка) — каждый multi-tenant call = TypeError.
  2. **OSINT fail-OPEN** (Workstream I, 1 dev-day) — compliance risk.
  3. **PII fail-OPEN** (Workstream B, 2-3 dev-days) — DSL + RAG + Security.
  4. **SAML + admin_cron RCE + ScriptRunner RCE + PickleDataFormat RCE** (Workstreams C+D, 3-5 dev-days) — security-critical.
  5. **Temporal Worker lifecycle** (Workstream E, HIGH risk, 1 sprint) — staging/prod profile.
  6. **MQ DLQ + webhook HMAC** (Workstream F, 2-3 dev-days).
  7. **HITL cross-tenant + AgentMemory tenant** (Workstream G, 2-3 dev-days).
  8. **Agents DSL registration + PII/guards** (Workstream H, 2-3 dev-days).
  9. **Settings + dependencies cleanup** (Workstream K, 1-2 dev-days).
  10. **Tests cleanup** (Workstream J, 1-2 dev-days, parallel).

- **Top P0-P1 для каждого домена** (см. §9).

- **Contradictions count**: 10 (см. §5) — все требуют верификации архитектором/разработчиком, не разрешаются чтением source.

- **Phase 3 candidate workstreams**: 14 (A..N, см. §6).

- **Library replacement candidates**: 12 (см. §7), из них **P0 drop-in** 4 (defusedxml, joserfc, HTTPBasic, tenacity для RAG). **P3 candidates** 8 (большинство обосновано отложены).

- **Organic features (P4)**: 22, **все defer** (cycle 5+ или cycle 6+).

- **Output файл**: `docs/audit/swarm-2026-08-06/cycle-4/PHASE-2-SUMMARY.md`.

- **Не верифицировалось** (по инструкции): source-код, тесты, git diff/log, cycle-1/2/3 markdown, CLAUDE/PLAN/KNOWN_ISSUES, журналы техдолга.

---

## 11. Что НЕ проверялось (явно по инструкции Phase 2)

- Source-код (`src/`, `extensions/`, `tests/`) — read-only scope, не выполнялось никаких изменений.
- Git diff/log — не выполнялись никакие git-команды.
- Cycle-1/2/3 markdown — `docs/audit/swarm-2026-08-06/cycle-{1,2,3}/**` ЗАПРЕЩЕНО читать.
- `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` — ЗАПРЕЩЕНО.
- Журналы техдолга (TECH_DEBT.md и аналогичные) — ЗАПРЕЩЕНО.
- `.env*`, `secrets/**` — ЗАпрещены permission rules (per AGENTS.md).
- Network checks (PyPI max-version, GitHub releases) — блокированы timeout (per dependency-домен отчёт).
- Любые модификации файлов — кроме создания `PHASE-2-SUMMARY.md` (per задаче).