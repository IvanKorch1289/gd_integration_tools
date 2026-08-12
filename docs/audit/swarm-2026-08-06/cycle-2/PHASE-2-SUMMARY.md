# Cycle 2 / Phase 2 — Сводный отчёт (Phase 2 Summary)

**Дата:** 2026-08-06
**HEAD:** `ca5bff93058f2580041a7339913b52943babb329` (cycle-2 baseline)
**Читались ТОЛЬКО:** `docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md` + 12 отчётов `phase-1/*.md`
**Запрещено к чтению:** исходный код, тесты, git diff/log, cycle-1 отчёты, CLAUDE/PLAN/KNOWN_ISSUES, KNOWN_ISSUES, locks, allowlist настоящего режима модификации. Source/lockfile/allowlist/s3.py/blue_green не модифицировались.
**Суммаризатор:** Kimi Code как pure Phase-2 summarizer, read-only.

---

## 1. Executive Summary

### 1.1 Состояние роя

12 аналитиков Phase 1 завершили bounded read-only аудит 12 доменов на `ca5bff93`. Каждый отчёт содержит собственный scoring (формула penalty per P0/P1/P2/P3/P4) и явное перечисление strengths / blockers / cycle-1 residuals / unverified. **Формулы различаются между доменами и НЕСОПОСТАВИМЫ напрямую** — это self-assessment, не глобальное сравнение. Используются здесь только как self-reported каждого домена.

### 1.2 Gate-Status (по BASELINE.md, прямой прогон подтверждён всеми 12 отчётами)

| Метрика | Значение | Подтверждение |
|---|---|---|
| `python tools/check_layers.py --root src` | exit 0, **0 new / 175 legacy** (2273 файлов) | 12/12 отчётов |
| `wc -l tools/check_layers_allowlist.txt` | **180** (5 header-комментов + 175 src-entries) | 12/12 |
| `grep -vE "^#\|^$" tools/check_layers_allowlist.txt \| wc -l` | **175** | 11/12 (явно: 02, 06, 09, 11, 12) |
| `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | **35 active** | 12/12 |
| `make check-docstrings MAX_ALLOWED=0` | 0 missing (838 файлов) | BASELINE |
| Pre-existing drift | `M uv.lock -15 svcs`, `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state` | НЕ атрибутируется рою cycle 2 |
| 5 uncommitted source правок cycle 1 Phase 4 | T-1.4 / T-1.5 / T-3.1 (gateway_pipeline_mixin, redelivery_policy, multicast, embedding_cache, gateway_adapter) | НЕ атрибутируется рою cycle 2 |

### 1.3 Заявленный рост 173 → 180 — КОНСЕНСУС

**Единый вердикт всех 12 отчётов: реального роста layer-violations НЕТ.**

- **175 legacy / 0 new** — стабильно между `b69d6b49` (cycle-1 baseline) и `ca5bff93` (cycle-2 baseline). `git diff b69d6b49 ca5bff93 -- tools/check_layers_allowlist.txt` = **пусто** (отчёты 06, 09, 11).
- 180 = 175 src-entries + 5 строк `#`-комментариев. **5 header-строк = не violations**, а пояснения формата.
- Цифра «173» в задании, по всей видимости, либо WC-L была +7 меньше, либо historical-snapshot, не совпадающий с checker-meta «175 legacy». Семантика «175» vs «180» — **разные метрики, не противоречие**.
- Organic прирост в `[33→38]` циклов (`df7ed563` billing.py, `674c8c1f` importlib-bypass) объясняет +7 entries между cycle-1 baseline и cycle-2, но это **НЕ атрибуция роя cycle 2**. Все 12 отчётов сходятся в этой интерпретации.

### 1.4 Top-of-mind risks (consolidated)

**Топ-критичные P0/P1, блокирующие порог ≥80 по ВСЕМ отчётам:**

1. **Auth bypass / fail-open:** SSE `principal/permissions` (04-P0-001), CDC+Filewatcher management no-auth (04-P0-003), MQTT no-auth (04-P0-004), AuthValidateProcessor broken (02-P0-003), sync `AuthorizationGateway.check` bypasses OPA/Casbin (02-P0-004), deprecated shim active (02-P0-002), hitl no auth (05-P0-004), mobile/router fail-open (05-P0-005), admin_cron RCE via importlib (05-P1-010).
2. **Data loss / fail-open:** CDC DLQ writer failure (01-P0-001), MQ subscribers ACK instead of DLQ (04-P0-002), `_maybe_mask_pii` PII unmasked on sanitizer fail (09-P0-003), RagCachePrewarmer silent no-op (09-P0-002), `_from_msgpack` pickle fallback RCE (06-P2-006 DSL).
3. **Broken imports / production crash:** `get_ai_agent_service` NotImplementedError × 7 callsites (08-P0-006), `LangGraphAgentProcessor` TypeError (08-P0-005), `_bootstrap_default_declarations` imports nonexistent saga modules (07-P0-005, 10-P0-002), stale `INFRA_MODULES["repos.files"]` (10-P0-001), `generator/setup.py` broken import (05-P0-003), `orders_dsl.py` uses non-existent `.then()` (07-P0-001).
4. **Credit scoring fail-OPEN (banking-critical):** `base_score=750` default for unknown (10-P0-003), OSINT report fabrication (10-P0-004).
5. **Production-startup blocker:** `--shutdown-timeout` is invalid for Granian 2.8.0 (12-P0-001), hardcoded shutdown timeout (12-P1-003).
6. **Architecture layer violations:** DSL→infra runtime-importlib (02-P1-001, 08-P0-004), extension→infra dynamic import (10-P1-001).
7. **Security/CVE drift:** `pip_audit_gate.py` hardcoded `IGNORED_VULNS` ≠ allowlist ≠ CI shell-flags (11-P0-001/003/P1-003), 9 CVE already fixed in installed versions but still in allowlist (11-P0-002), streamlit open-ended ≥1.58.0 (11-P0-004).
8. **Workflow broken bridge:** `ActivityBridge` not used in production worker (07-P0-003), `TemporalWorkerPool` never instantiated (07-P0-004), 4 workflow processors unregistered (07-P0-002).
9. **Agent DSL PII/audit lineage:** hardcoded `tenant_id="default"|"unknown"` (08-P0-003).
10. **Business logic fail-open:** OSINT template-placedholders as report (10-P0-004).

---

## 2. Домены — итоговая таблица

Readiness score приводится **как self-reported** соответствующим доменом (формулы НЕСОПОСТАВИМЫ между доменами). P0..P4 — counts.

| # | Домен | Readiness (self) | P0 | P1 | P2 | P3 | P4 | Всего | Top strengths | Top blockers | Cycle-1 residuals | Unverified |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | Infrastructure | 45/100 | 1 | 3 | 2 | 1 | 0 | 7 | Layer checker exit 0, CDC DLQ guard wired, Webhook scheme/HMAC, S3 multipart abort | `DOMAIN-P0-001` CDC DLQ writer failure silent data-loss | cycle-1 IDs `DOMAIN-P0-001..007` НЕ сопоставлены (запрет чтения); базовый evidence проверен live | Cycle-1 конкретные IDs/paths не читал; только собственный scoped grep |
| 02 | Security | 35/100 (raw 0) | 4 | 3 | 5 | 2 | 0 | 14 | OPA runtime HTTP/2 + connection pool, fail-closed, CapabilityPolicy deny>allow, short-circuit AuthorizationGateway, IPRestrictionStore DCL, JdbcQuery SQL-injection blocklist, InMemoryJwtBlacklist with TTL | `DOMAIN-P0-003` AuthValidateProcessor broken, `DOMAIN-P0-004` sync check bypasses OPA/Casbin, `DOMAIN-P0-001` validate_sql policy_override drop, `DOMAIN-P0-002` deprecated shim 5 active consumers | DOMAIN-P0-001/002 RESIDUAL; 003/004 NEW | session-id SAML race, mcp auth private-symbol use, sandbox timing |
| 03 | Services | 22/100 | 1 | 4 | 4 | 1+1(N) | 1 | 11+1 | FacadeCapabilityAdapter, route_authz fail-closed, canonical DLQWriter Protocol, retry_async in audit emit, `core/audit/facade` canonical, QuotasService stub fail-fast, replay_query placement fix | `DOMAIN-SVCS-P0-001` AdminService fail-open (dead code), `DOMAIN-SVCS-P1-001` 5-way data_quality dup (MUTATED 4→5), `DOMAIN-SVCS-P1-004` AdminService dead 244 LOC | RESIDUAL: P0-001, P1-002/003, P2-001; MUTATED: P1-001 (5-way); PARTIALLY MUTATED: P2-001/002/005 | Cycle-1 конкретные IDs `DOMAIN-P1-...`/`P3-001` only via cross-domain grep; нельзя сверить |
| 04 | Entrypoints | 4/100 | 4 | 4 | 2 | 2 | 0 | 12 | SOAP/GraphQL/WS auth parity-pattern, ExecutionContext.from_auth, WAF/CDC DLQ infra, MQTT TLS, IMAP Vault, B-17 fail-loud wired | `DOMAIN-P0-001` SSE principal/permissions (8 xfail xfail), `DOMAIN-P0-002` MQ ACK вместо DLQ, `DOMAIN-P0-003` CDC+Filewatcher management no auth, `DOMAIN-P0-004` MQTT no auth | RESIDUAL: P0-001, P0-002, P1-001; NEW: P0-003/004, P1-002/003/004 | gRPC servicer-flow, MCP helpers, ws_broadcast, http3 internals |
| 05 | API | 0/100 (clamped) | 5 | 3 | 2 | 1 | 0 | 11 | AuthRequiredMiddleware pure ASGI, 9 admin routers with `require_admin`, routers.py 365 LOC собрано, schemas Camel alias, VersionedRouter/DeprecationMiddleware, mobile_router orphan (не mounted) | `API-P0-001/002` admin_* silent-success mock-fallback, `API-P0-003` generator/setup.py broken import, `API-P0-004` hitl no auth, `API-P0-005` mobile fail-open (dead), `API-P1-010` admin_cron RCE via importlib | RESIDUAL: P0-001/002/003/004; MUTATED: P0-005 (dead-code-isolated); NEW: P1-NEW-001 | extensions полностью, services реализации, AuthRequiredMiddleware в deploy |
| 06 | DSL | 67/100 | 3 | 10 | 11 | 4 | 3 | 31 | T-1.4 multicast/redelivery fix verified, defusedxml в marshal (transitive), xmltodict 0.15.1, 342 eip tests PASS, 23 scan_file tests PASS, 65+ capability-required declarations, handle_processor_error fail-closed | `DSL-P0-001` ScanFile fail-open warn mode, `DSL-P0-002/003` XML XXE fallback (latent), `DSL-P1-001` 3× XML helpers dup, `DSL-P1-009` 58 undecorated BaseProcessor, `DSL-P2-001` 442 LOC dead reliability.py | ALL 14 cycle-1 DSL findings RESIDUAL (DSL-P0-002 → DSL-P0-002 was RESOLVED via T-1.4) | cycle-1 ID `DOMAIN-P1-007` (alt) дважды в residuals table; `defusedxml` direct dep не в pyproject (transitive only) |
| 07 | Workflow | 0/100 (clamped) | 5 | 3 | 6 | 3 | 3 | 20 | 3 production backends (Temporal/Lite/PgRunner), Saga semantics, BPMN→WorkflowDeclaration, StepAuditMiddleware, HITL Redis pub/sub, DurableWorkflowRunner LISTEN/NOTIFY, compile_workflow idempotent | `DOMAIN-WF-P0-001` WorkflowFlags docstring lie (4× default=True), `DOMAIN-WF-P0-002` 4 unregistered processors, `DOMAIN-WF-P0-003` ActivityBridge не используется, `DOMAIN-WF-P0-004` TemporalWorkerPool никогда не инстанцируется, `DOMAIN-WF-P0-005` bootstrap saga imports nonexistent | RESIDUAL: 4 в scope (P0-001/002/003/004) | Saga e2e в Temporal cluster; production Temporal path не использует compile_workflow output |
| 08 | Agents | 49/100 | 4 | 4 | 2 | 1 | 1 | 12 | T-1.5 fix verified (dual-signature detection, AIGatewayCompositionRoot DI), CapabilityFacade thread-safe cache, fail-closed `_policy_gate`, FastMCP capability-gate, AgentRun tenant_id correct, MCPTool deny file://, query-length cap | `DOMAIN-P0-005` LangGraph TypeError (production crash), `DOMAIN-P0-006` get_ai_agent_service NotImplementedError × 7 callsites, `DOMAIN-P0-003` 3 hardcoded tenant_id, `DOMAIN-P0-004` fastmcp_server DSL→infra coupling | RESIDUAL: P0-003/004, P1-002/003/004, P2-001/002/003; RESOLVED: P0-001/002 (T-1.5); MUTATED: P1-001 | pydantic_ai_client.py 644 LOC полностью, vendor libs (langgraph/mcp/litellm), extensions |
| 09 | RAG | 59/100 | 4 | 2 | 2 | 1 | 1 | 10 | Tenant isolation 3-tier (cache+where+post-filter), three-tier cache (L1/L2/L3), 26 cache tests PASS, retrieval strategies heuristic fallback, PII redaction (Presidio + legacy), multimodal E2E, embed version filter | `RAG-P0-001` PII fail-open single-doc API (7 xfail), `RAG-P0-002` RagCachePrewarmer silent no-op (runtime-verified `Loaded: 0`), `RAG-P0-003` PII fail-open sanitizer exception, `RAG-P0-004` phantom fill_cache param | RESIDUAL: P0-001, P0-002, P2-001, P4-001 (text-RAG E2E) | network vendor Qdrant/Redis, BLIP2/Whisper stubs, perf-bench |
| 10 | Business Logic | 0/100 (clamped) | 4 | 2 | 4 | 2 | 1 | 13 | Repository facade pattern enforced, calculate_combined_score fail-CLOSED, Pydantic v2 Literal + Field validation, plugin.toml compliance, CreditPipelinePlugin idempotent | `DOMAIN-P0-001` repos.files/orders stale registry (ModuleNotFoundError), `DOMAIN-P0-002` workflow_setup saga imports (default OFF), `DOMAIN-P0-003` credit scoring fail-OPEN (base_score=750), `DOMAIN-P0-004` OSINT report fabrication (template as report) | ALL 4 cycle-1 P0 in scope verified RESIDUAL | email-validator missing в env — pytest collection blocked; extensions full audit не проводился |
| 11 | Dependencies | 30/100 | 4 | 3 | 5 | 1 | 1 | 14 | Pinned narrow ranges, force-pinned transitive blocks, `[tool.uv].override-dependencies`, CI gate orchestration, `make audit-deps` correctly consumes allowlist, preflight gate | `DOMAIN-P0-001` 4-way CVE drift (hardcoded vs file vs CI shell), `DOMAIN-P0-002` 9 CVE already fixed in lockfile (false-positive carryover), `DOMAIN-P0-003` `pip_audit_gate.py` не читает allowlist, `DOMAIN-P0-004` `streamlit>=1.58.0` open-ended | VERIFIED: P0-001 (4-way drift), P0-002 (8+ CVE), P0-003 (false comment), P0-004 (drift), P2-001 (sphinx dead), P2-002 (phantom-version), P2-003 (diskcache), P2-005 (streamlit); REFUTED-MUTATED: P2-004 (9 vs 4 confirmed) | license/maintenance risk не проверено, network PyPI live lookup |
| 12 | Settings-Environment | 47/100 (cap 79) | 2 | 2 | 3 | 3 | 2 | 12 | Single YAML overlay, Vault+Consul fail-silent, ConfigValidator 14 checks fail-closed, hot_reload watchfiles+debounce, k8s securityContext/preStop/seccomp, compose healthchecks, extension boundary | `ENVSET-C2-P0-001` Granian `--shutdown-timeout` invalid (2.8.0 needs `--workers-kill-timeout`), `ENVSET-C2-P0-002` `graceful_shutdown_timeout` duplicate field с разными env_prefix, `ENVSET-C2-P1-003` shutdown timeout hardcoded 10s vs 30s k8s, `ENVSET-C2-P1-004` compose без cgroup limits | RESIDUAL: 5/13 (P0-001/002, P1-001/004, P2-001); MUTATED/CLOSED: P1-003 (k8s preStop); NOT VERIFIED: 7 | production enterpoint `manage.py` vs `tools/granian_runner.py` — какой path активен не подтверждён |

**Totals:** 12 доменов, **52 P0, 49 P1, 51 P2, 24 P3, 14 P4 = 190 findings** (с нюансами: 03 имеет +1 P3 note, 06 имеет 3 P4). Self-reported readiness не нормируется по общей формуле — каждое domain-уникальное.

---

## 3. Нормализованный реестр findings (P0 → P4)

Глобальный ключ: `<domain>:<original-id>`. Все оригинальные ID/path/evidence сохранены. Cross-domain corroboration помечена отдельно.

### 3.1 P0 (data-loss / security / race / fail-open) — 52 находок

| Global key | Domain | Original ID | Title | Path:line | Cross-domain corroboration |
|---|---|---|---|---|---|
| 01:DOMAIN-P0-001 | Infrastructure | DOMAIN-P0-001 | CDC DLQ writer failure silent data-loss (logged `EVENT WILL BE LOST`, no retry) | `src/backend/infrastructure/clients/external/cdc/client.py:323-334` | overlap with 04:DOMAIN-P0-002 (MQ subscribers ACK вместо DLQ), 03:DOMAIN-SVCS-P2-005 (DLQ priority-3 silent_loss) |
| 02:DOMAIN-P0-001 | Security | DOMAIN-P0-001 | `validate_sql` теряет `policy_override` (RESIDUAL) | `src/backend/services/agent_security/facade.py:121-133` | standalone |
| 02:DOMAIN-P0-002 | Security | DOMAIN-P0-002 | deprecated `auth_selector` shim всё ещё активно используется (5 prod consumers + 1 DSL + 2 tests) | `src/backend/entrypoints/api/dependencies/auth_selector.py` + 5 consumers | standalone |
| 02:DOMAIN-P0-003 | Security | DOMAIN-P0-003 | `AuthValidateProcessor._load_verifiers()` returns `{}` → bypass при `required=False`, hard fail при `required=True` | `src/backend/dsl/engine/processors/security.py:32-55, 73-117` | standalone |
| 02:DOMAIN-P0-004 | Security | DOMAIN-P0-004 | sync `AuthorizationGateway.check()` обходит OPA/Casbin (always falls through to in-memory dict) | `src/backend/core/security/authorization_gateway/__init__.py:249-309, 357-383` | standalone |
| 03:DOMAIN-SVCS-P0-001 | Services | DOMAIN-SVCS-P0-001 | `AdminService._authorize()` fail-open при `authz is None` (dead code class) | `src/backend/services/admin/api.py:96-102` | standalone |
| 04:DOMAIN-P0-001 | Entrypoints | DOMAIN-P0-001 | SSE `/events/invoke` не пробрасывает `principal`/`permissions` из `request.state.auth` (8 xfail strict) | `src/backend/entrypoints/sse/handler.py:178-219` + `_action_bridge.py:86-87` | overlap with 04:DOMAIN-P1-002 (WS/Webhook/Express та же проблема) |
| 04:DOMAIN-P0-002 | Entrypoints | DOMAIN-P0-002 | MQ Redis+RabbitMQ subscribers ACK вместо DLQ enqueue (B-17 fail-loud pattern НЕ применён) | `src/backend/entrypoints/stream/{subscribers,invoker_subscribers}.py` | overlap with 01:DOMAIN-P0-001 (CDC DLQ handoff), 03:DOMAIN-SVCS-P2-005 (DLQ priority-3) |
| 04:DOMAIN-P0-003 | Entrypoints | DOMAIN-P0-003 | CDC + Filewatcher management endpoints без auth (public POST/DELETE/GET) | `src/backend/entrypoints/cdc/cdc_routes.py:38-70`, `src/backend/entrypoints/filewatcher/watcher_routes.py:33-69` | standalone |
| 04:DOMAIN-P0-004 | Entrypoints | DOMAIN-P0-004 | MQTT handler без auth/principal/permissions (fail-open для всех MQTT-подписчиков) | `src/backend/entrypoints/mqtt/mqtt_handler.py:131-157` | contrast with WS auth on handshake (S172 M1.1) |
| 05:API-P0-001 | API | API-P0-001 | admin_actions silent-success mock-fallback на POST /invoke | `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:206-214` | overlap with 05:API-P0-002 (admin_plugins analog) |
| 05:API-P0-002 | API | API-P0-002 | admin_plugins silent-success mock-fallback на POST /{name}/toggle | `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py:267-277` + дубль `endpoints.py:145-155` | overlap with 05:API-P0-001 |
| 05:API-P0-003 | API | API-P0-003 | generator/setup.py broken import `src.backend.workflows.workflows_service` (4 вхождения) | `src/backend/entrypoints/api/generator/setup.py:12-14` | standalone |
| 05:API-P0-004 | API | API-P0-004 | hitl.py no router-level auth guard (вся auth полагается только на global middleware) | `src/backend/entrypoints/api/v1/endpoints/hitl.py:48-129` | overlap with 04:DOMAIN-P0-001 (SSE/HITL — T-1.2 deferred) |
| 05:API-P0-005 | API | API-P0-005 | mobile/router.py fail-open token parser + in-memory state (router orphan не mounted) | `src/backend/entrypoints/api/mobile/router.py:55-93` | standalone (dead-code-isolated) |
| 06:DSL-P0-001 | DSL | DSL-P0-001 | ScanFileProcessor fail-open в `on_threat="warn"` + AV backend unavailable | `src/backend/dsl/engine/processors/scan_file.py:78-97` | standalone (test `test_scan_file_backend_unavailable_warn_mode_does_not_fail` masks bug) |
| 06:DSL-P0-002 | DSL | DSL-P0-002 | XML XXE fallback path в format_convert (latent) | `src/backend/dsl/engine/processors/format_convert/{data_formats,encodings,specialized}.py:63,65,63` | overlap with 06:DSL-P0-003 (marshal XXE) |
| 06:DSL-P0-003 | DSL | DSL-P0-003 | `XmlDataFormat.unmarshal()` XXE fallback (latent) | `src/backend/dsl/engine/processors/eip/marshal/formats.py:138-140` | overlap with 06:DSL-P0-002 |
| 07:DOMAIN-WF-P0-001 | Workflow | DOMAIN-WF-P0-001 | WorkflowFlags docstring lie: 4/5 флагов `default=True` но docstring говорит "default-OFF" | `src/backend/core/config/features/workflow.py:33-73` | standalone |
| 07:DOMAIN-WF-P0-002 | Workflow | DOMAIN-WF-P0-002 | 4 workflow processors (`workflow_subprocess`, `workflow_convert`, `best_practices/claim_check`, `best_practices/continue_as_new`) без `@processor` | `src/backend/dsl/engine/processors/workflow/{workflow_subprocess,workflow_convert}.py`, `workflow/best_practices/{claim_check,continue_as_new}.py` | overlap with 06:DSL-P1-009 (58 undecorated prod processors) |
| 07:DOMAIN-WF-P0-003 | Workflow | DOMAIN-WF-P0-003 | ActivityBridge (356 LOC) написана, но production worker использует `DSLStepExecutor`, не `@workflow.defn` | `src/backend/dsl/workflow/compiler/activity_bridge.py:1-356` | overlap with 07:DOMAIN-WF-P0-004 (TemporalWorkerPool never instantiated) |
| 07:DOMAIN-WF-P0-004 | Workflow | DOMAIN-WF-P0-004 | `TemporalWorkerPool` (94 LOC) определён, но никогда не инстанцируется (только docs/tutorials) | `src/backend/infrastructure/workflow/temporal_client.py:227-320` | overlap with 07:DOMAIN-WF-P0-003 |
| 07:DOMAIN-WF-P0-005 | Workflow | DOMAIN-WF-P0-005 | `_bootstrap_default_declarations` импортирует несуществующие `orders_saga`/`payments_saga` | `src/backend/plugins/composition/workflow_setup.py:76-83` | overlap with 10:DOMAIN-P0-002 (saga imports cross-scope) |
| 08:DOMAIN-P0-003 | Agents | DOMAIN-P0-003 | 3 Agent DSL hardcoded `tenant_id="default"|"unknown"` (audit lineage broken) | `dsl/engine/processors/agent_dsl/{ai_tool_dispatch:251,plan_execute:270,reflection_loop:254}.py` | standalone; contrast: `agent_run.py:137` correctly reads `exchange.meta.tenant_id` |
| 08:DOMAIN-P0-004 | Agents | DOMAIN-P0-004 | fastmcp_server.py direct `infrastructure.workflow.registry` import (DSL→infra reverse coupling) | `src/backend/dsl/agents/fastmcp_server.py:36-39` | overlap with 02:DOMAIN-P1-001 (DSL→entrypoints runtime importlib) |
| 08:DOMAIN-P0-005 | Agents | DOMAIN-P0-005 | `LangGraphAgentProcessor.process()` TypeError — `build_and_run_agent(query=..., thread_id=..., max_iterations=...)` invalid signature | `src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py:73-78` | standalone (tests mock `build_and_run_agent`, masks bug) |
| 08:DOMAIN-P0-006 | Agents | DOMAIN-P0-006 | `get_ai_agent_service()` raise NotImplementedError × 7 production callsites (LLM-action subsystem broken) | `src/backend/services/ai/ai_agent/__init__.py:109-111` + 7 callsites | overlap with 08:DOMAIN-P1-003 (export contract) |
| 09:RAG-P0-001 | RAG | RAG-P0-001 | PII fail-open на single-doc API (7 xfail strict) | `entrypoints/api/v1/endpoints/rag.py:212, 332` | standalone |
| 09:RAG-P0-002 | RAG | RAG-P0-002 | RagCachePrewarmer silent no-op (runtime-verified `Loaded: 0, Store query calls: 0`) | `src/backend/services/ai/rag_cache_prewarmer.py:69` | overlap with 09:RAG-P0-004 (phantom `fill_cache` parameter) |
| 09:RAG-P0-003 | RAG | RAG-P0-003 | `_maybe_mask_pii` fail-open при сбое sanitizer (банковский 152-ФЗ) | `src/backend/services/ai/rag_ingest_service.py:224-226` | contrast with 09:RAG-P0-001 (fail-open facade) |
| 09:RAG-P0-004 | RAG | RAG-P0-004 | Phantom `fill_cache` parameter (нет в сигнатурах RAGService) | `src/backend/services/ai/rag_cache_prewarmer.py:69` | overlap with 09:RAG-P0-002 |
| 10:DOMAIN-P0-001 | Business Logic | DOMAIN-P0-001 | `INFRA_MODULES["repos.files"]`/`["repos.orders"]` stale (ModuleNotFoundError) | `src/backend/core/di/module_registry.py:136-137` | overlap with 10:DOMAIN-P1-002 (FileService runtime failure) |
| 10:DOMAIN-P0-002 | Business Logic | DOMAIN-P0-002 | `_bootstrap_default_declarations` импортирует несуществующие saga модули | `src/backend/plugins/composition/workflow_setup.py:76-83` | overlap with 07:DOMAIN-WF-P0-005 |
| 10:DOMAIN-P0-003 | Business Logic | DOMAIN-P0-003 | credit scoring fail-OPEN: `base_score=750` default для unknown → APPROVED | `extensions/credit_pipeline/agents/__init__.py:84-94` | standalone (banking-critical) |
| 10:DOMAIN-P0-004 | Business Logic | DOMAIN-P0-004 | OSINT workflow fail-OPEN: template placeholders parsed as report sections | `extensions/osint_agent/functions/osint_workflow.py:305-334` | standalone (data fabrication) |
| 11:DOMAIN-P0-001 | Dependencies | DOMAIN-P0-001 | 4-way CVE drift: hardcoded `IGNORED_VULNS` vs file-allowlist vs CI shell-flags | `.security/pip-audit-allowlist.txt:16,79` + `pyproject.toml:137` + `tools/pip_audit_gate.py:19-21` | overlap with 11:DOMAIN-P0-003 |
| 11:DOMAIN-P0-002 | Dependencies | DOMAIN-P0-002 | 9 CVE already fixed in lockfile but still in allowlist (false-positive carryover) | `.security/pip-audit-allowlist.txt:16-79` vs `uv.lock` | standalone |
| 11:DOMAIN-P0-003 | Dependencies | DOMAIN-P0-003 | `pip_audit_gate.py` IGNORED_VULNS hardcoded ≠ allowlist file ≠ CI shell-flags | `tools/pip_audit_gate.py:14-22` vs `.github/workflows/security.yml:133-139` | overlap with 11:DOMAIN-P0-001, 11:DOMAIN-P1-003 |
| 11:DOMAIN-P0-004 | Dependencies | DOMAIN-P0-004 | `streamlit>=1.58.0` open-ended pin в `[project].dependencies` | `pyproject.toml:137` | standalone |
| 12:ENVSET-C2-P0-001 | Settings-Environment | ENVSET-C2-P0-001 | Granian `--shutdown-timeout` flag invalid for 2.8.0 (needs `--workers-kill-timeout`) | `src/backend/core/scaling/granian_tuning.py:222-223` | standalone |
| 12:ENVSET-C2-P0-002 | Settings-Environment | ENVSET-C2-P0-002 | `graceful_shutdown_timeout` duplicate field с разными env_prefix (`APP_` vs `GRANIAN_`) и validations | `src/backend/core/config/base/app_base.py:115-124` + `src/backend/core/scaling/granian_tuning.py:125-135` | standalone |

### 3.2 P1 (architecture / layer boundaries / parity) — 49 находок

| Global key | Domain | Original ID | Title |
|---|---|---|---|
| 01:DOMAIN-P1-001 | Infrastructure | DOMAIN-P1-001 | `event_bus.py:151-169` imports `services.schema_registry.registry` (reverse-layer) |
| 01:DOMAIN-P1-002 | Infrastructure | DOMAIN-P1-002 | `semantic.py:55-67` lazy-imports `services.ai.embedding_providers` (fail-open degradation) |
| 01:DOMAIN-P1-003 | Infrastructure | DOMAIN-P1-003 | `scheduled_tasks.py:55-61` imports services AI memory direct |
| 02:DOMAIN-P1-001 | Security | DOMAIN-P1-001 | DSL → entrypoints runtime importlib violation (security.py:5-14) |
| 02:DOMAIN-P1-002 | Security | DOMAIN-P1-002 | `_verify_saml` trust header/cookie без session signature check |
| 02:DOMAIN-P1-003 | Security | DOMAIN-P1-003 | `mcp/auth_middleware.py` doc/import drift + use private `_verify_api_key`/`_verify_jwt` |
| 03:DOMAIN-SVCS-P1-001 | Services | DOMAIN-SVCS-P1-001 | 5-way data_quality duplication (MUTATED 4→5) с class identity mismatch |
| 03:DOMAIN-SVCS-P1-002 | Services | DOMAIN-SVCS-P1-002 | `services/io/files.py` shim (20 LOC, 3 active callers) |
| 03:DOMAIN-SVCS-P1-003 | Services | DOMAIN-SVCS-P1-003 | `services/integrations/skb.py` shim + production mix (152 LOC) |
| 03:DOMAIN-SVCS-P1-004 | Services | DOMAIN-SVCS-P1-004 | `AdminService` dead public API 244 LOC |
| 04:DOMAIN-P1-001 | Entrypoints | DOMAIN-P1-001 | `subscribers.py:9` imports through `api.generator.registry` (anti-pattern) |
| 04:DOMAIN-P1-002 | Entrypoints | DOMAIN-P1-002 | WS/Webhook/Express не передают principal в bridge (parity gap with SSE) |
| 04:DOMAIN-P1-003 | Entrypoints | DOMAIN-P1-003 | MCP `route_execute` tool bypasses permission (direct `engine.execute`) |
| 04:DOMAIN-P1-004 | Entrypoints | DOMAIN-P1-004 | IMAP + Filewatcher dispatch без context (system events anonymous) |
| 05:API-P1-004 | API | API-P1-004 | `admin_nats` dynamic layer violation (importlib bypass) |
| 05:API-P1-010 | API | API-P1-010 | `admin_cron` importlib без sandbox allowlist (RCE via `os:system`) |
| 05:API-P1-NEW-001 | API | API-P1-NEW-001 | invocations POST без router-level auth (RPC-scall for all) |
| 06:DSL-P1-001 | DSL | DSL-P1-001 | 3× XML helpers duplication (108 LOC) |
| 06:DSL-P1-002 | DSL | DSL-P1-002 | `EventMessage._publish_count` counter naming (success+fail merged) |
| 06:DSL-P1-003 | DSL | DSL-P1-003 | `MessageTranslator._xml_to_dict` regex fallback |
| 06:DSL-P1-004 | DSL | DSL-P1-004 | `MessageTranslator._csv_*` polars fallback |
| 06:DSL-P1-005 | DSL | DSL-P1-005 | `BatchAggregatorProcessor` orphan (not BaseProcessor) |
| 06:DSL-P1-006 | DSL | DSL-P1-006 | `eip.routing_slip.ProcessorRegistry` name collision |
| 06:DSL-P1-007 | DSL | DSL-P1-007 | `audit.py` no `@processor` decorator |
| 06:DSL-P1-008 | DSL | DSL-P1-008 | `scan_file.py` no `@processor` decorator |
| 06:DSL-P1-009 | DSL | DSL-P1-009 | 58 undecorated BaseProcessor classes (cycle-38 B-04 sample incomplete) |
| 06:DSL-P1-010 | DSL | DSL-P1-010 | 2× `_legacy.py` 1 LOC stub files |
| 07:DOMAIN-WF-P1-001 | Workflow | DOMAIN-WF-P1-001 | `orders_dsl.py` uses non-existent `.then()` (production extension broken) |
| 07:DOMAIN-WF-P1-002 | Workflow | DOMAIN-WF-P1-002 | `WorkflowCostEstimator` silent fallback (LLM cost = 0 USD) |
| 07:DOMAIN-WF-P1-003 | Workflow | DOMAIN-WF-P1-003 | Legacy `GatewayCompiler` dead code 137 LOC |
| 08:DOMAIN-P1-001 | Agents | DOMAIN-P1-001 | `try/except Exception` в `_check_capability` swallows `CapabilityDeniedError` |
| 08:DOMAIN-P1-002 | Agents | DOMAIN-P1-002 | `_build_ai_gateway_singleton` bare DI constructors (no vocab/policies/roots) |
| 08:DOMAIN-P1-003 | Agents | DOMAIN-P1-003 | `get_ai_agent_service` export contract (overlap with P0-006) |
| 08:DOMAIN-P1-004 | Agents | DOMAIN-P1-004 | `LiteLLMModel.request_stream` NotImplementedError + duplicate `LiteLLMModelAdapter` |
| 09:RAG-P1-001 | RAG | RAG-P1-001 | `POST /search` + `POST /augment` tenant isolation depends only on middleware |
| 09:RAG-P1-002 | RAG | RAG-P1-002 | `MultimodalPipeline` dead production path (175 LOC) |
| 10:DOMAIN-P1-001 | Business Logic | DOMAIN-P1-001 | `extensions/core_entities/orders/services/orders.py:413` dynamic import `infrastructure.external_apis.s3` |
| 10:DOMAIN-P1-002 | Business Logic | DOMAIN-P1-002 | `FileService` runtime fails (overlap with P0-001) |
| 11:DOMAIN-P1-001 | Dependencies | DOMAIN-P1-001 | 4 duplicate pin specs (rank-bm25, lxml, pyarrow, streamlit) |
| 11:DOMAIN-P1-002 | Dependencies | DOMAIN-P1-002 | `make docs-html`, `docs-multiversion`, `docs/api/` dead sphinx path |
| 11:DOMAIN-P1-003 | Dependencies | DOMAIN-P1-003 | 3 sources of truth for ignored CVEs (gate vs file vs CI) |
| 12:ENVSET-C2-P1-003 | Settings-Environment | ENVSET-C2-P1-003 | `shutdown.py:199` hardcoded `timeout=10` vs `settings.app.graceful_shutdown_timeout=30` |
| 12:ENVSET-C2-P1-004 | Settings-Environment | ENVSET-C2-P1-004 | `docker-compose*.yml` no cgroup limits (7 files, 823 LINES) |

### 3.3 P2 (dead code / dead branches / observability) — 51 находок

| Domain | P2 count | Типичные |
|---|---|---|
| 01 Infrastructure | 2 | `QueueFull` silent drop, abstract base NotImplementedError |
| 02 Security | 5 | Dead `OPAPolicyDecider`/`CasbinPolicyDecider` aliases, dead `_casbin_check`/`_opa_check`, CapabilityFacade exceptions swallowed, fire-and-forget audit coroutine |
| 03 Services | 4 | QuotasService stub, 9× `raise NotImplementedError # заменяется декоратором`, DLQ priority-3 silent_loss (PARTIALLY MUTATED) |
| 04 Entrypoints | 2 | `BaseEntrypoint` @deprecated dead class, `event_bus` singleton + CDC no tenant |
| 05 API | 2 | `mobile_router` orphan, empty `schemas/{filter_schemas,route_schemas}/__init__.py` (1 LOC each) |
| 06 DSL | 11 | `eip/reliability.py` 442 LOC shadowed, 3× XML helper dup, `_to_msgpack`/`_from_msgpack` pickle fallback RCE, `_from_html_unescape` no size cap, `BatchAggregatorProcessor` orphan, dead `audit.py` no `audit_event`, `eip/aggregation.py` not BaseProcessor, etc. |
| 07 Workflow | 6 | `COMPENSATE_SIGNAL` dead contract, `BpmnImportNotAvailableError` never raised, `WorkflowDiff`/`compute_step_diff` unused, `dryrun.py` CLI-only, `SlaTracker` no consumer, `StepAuditMiddleware` not wired |
| 08 Agents | 2 | Stale docstring `ai_tool_dispatch.py:22-25` (scaffold), `fastmcp_server.start/stop` no-op (0 callers) |
| 09 RAG | 2 | `RagCachePrewarmer` dead (P0-002), `AugmentMixin` style defect |
| 10 Business Logic | 4 | ES indexing swallow all, `OsintReport` dataclass unused, rule-based scoring placeholder, 4 scaffold TODOs |
| 11 Dependencies | 5 | dead sphinx path (P1-002 overlap), phantom-version gates, diskcache stale comment, duplicate pins, streamlit open-ended |
| 12 Settings-Environment | 3 | `graceful_shutdown_timeout` docstring, bare except in granian_tuning, `NotImplementedError` for DB types |

### 3.4 P3 (library replacement / dependency cleanup) — 24 находок

| Domain | P3 count | Top items |
|---|---|---|
| 01 Infrastructure | 1 | `search_providers.py:327-343` optional Tavily/SearXNG silent pass |
| 02 Security | 2 | Custom PII regex vs `presidio-analyzer` (уже в pyproject), in-memory policy парalel с engine |
| 03 Services | 1+1 note | `retry_async` vs `tenacity` (already in deps); `apprise` lazy import (positive pattern) |
| 04 Entrypoints | 2 | `faststream.*.fastapi` deprecated → `faststream_fastapi`; custom retry → `tenacity` |
| 05 API | 1 | `schemas/invocation.py` shim (20+ importers) |
| 06 DSL | 4 | XML helpers DRY → xmltodict; pickable fallback removal; remove polars fallback; scan_file cascade |
| 07 Workflow | 3 | `SlaTracker` integration, `SagaHistoryService`/`HitlHistoryService` unused, `StepAuditMiddleware` not wired |
| 08 Agents | 1 | DSPy trainer DI keys not registered (optimize_prompt dead) |
| 09 RAG | 1 | `rank_bm25` for token-overlap fallback |
| 10 Business Logic | 2 | SKB error messages, osint `_scrape_url` direct httpx (vs `OutboundHttpClient` facade) |
| 11 Dependencies | 1 | rank-bm25 candidate for consolidation |
| 12 Settings-Environment | 3 | DatabaseConnectionSettings mixin, hvac, watchfiles (all OK as-is) |

### 3.5 P4 (organic features) — 14 находок

Mostly organic features that may be deferred:
- 03:01 — `list_audit_records` ClickHouse fallback (DR scenario)
- 06:03 — marshal, SortProcessor, templates_library (YAGNI)
- 07:03 — BPMN multi-instance, Temporal workflow timeout-cancellation, library replacement for simpleeval/jmespath
- 08:01 — workflow_hooks public API unused (banking/RPA/code-gen)
- 09:01 — text-RAG E2E test (RESIDUAL, cycle 1 deferred)
- 10:01 — `credit_assessment.workflow.yaml` real Temporal workflow
- 11:01 — temporalio (already in deps)
- 12:02 — Test coverage for granian negative test, main.py `_run_granian` workers_kill_timeout

---

## 4. Приоритизация (P0 → P1 architecture → P2 dead → P3 library → P4 feature)

### 4.1 P0 — data-loss / security / race / fail-open (блокирует production)

**Критические кластеры (взаимосвязанные, требуют совместного решения):**

1. **Fail-open auth cluster:** 02-P0-002/003/004, 04-P0-001/003/004, 05-P0-004/005, 08-P0-006 (factory broken). Все связаны с L5 Security Chain migration (cycle 1 deferred T-1.2).
2. **Data-loss / DLQ cluster:** 01-P0-001, 04-P0-002, 03-SVCS-P2-005, 09-P0-002/004. B-17 fail-loud pattern не применён к MQ-транспорту.
3. **Broken imports / production crash:** 08-P0-005 (LangGraph TypeError), 08-P0-006 (get_ai_agent_service), 07-P0-005/10-P0-002 (saga imports), 10-P0-001 (repos.files stale), 05-P0-003 (generator/setup.py).
4. **Banking-critical fail-open:** 10-P0-003 (credit scoring), 10-P0-004 (OSINT fabrication).
5. **Production-startup blocker:** 12-P0-001 (Granian invalid flag).
6. **PII fail-open:** 02 (related), 08-P0-003 (audit lineage), 09-P0-001/003 (single-doc API + sanitizer exception).
7. **Security chains:** 02-P0-001 (validate_sql policy_override drop — RESIDUAL from cycle 1).
8. **CVE drift:** 11-P0-001/002/003/004 (security allowlist drift).
9. **Architecture systemic:** 07-P0-001 (WorkflowFlags lie), 07-P0-002 (4 unregistered processors), 07-P0-003 (ActivityBridge unused), 07-P0-004 (TemporalWorkerPool uninstantiated).

### 4.2 P1 — architecture / layer boundaries

**Критические кластеры:**

1. **Reverse-layer cluster:** 01-P1-001/002/003 (infrastructure→services direct imports), 02-P1-001 (DSL→entrypoints runtime), 08-P0-004 (DSL→infra), 10-P1-001 (extension→infra dynamic import).
2. **Permission/parity cluster:** 04-P1-002/003/004 (WS/Webhook/Express/MCP/IMAP/Filewatcher не передают principal), 02-P1-002 (SAML trust).
3. **Composition / DI cluster:** 08-P1-001 (CapabilityDeniedError swallow), 08-P1-002 (bare DI), 03-SVCS-P1-001 (5-way data_quality with class identity bug).
4. **Library replacement / dead code:** 06-P1-001..010 (XML helpers, undecorated processors, orphan classes), 03-SVCS-P1-002/003 (shims), 03-SVCS-P1-004 (AdminService dead), 11-P1-001/002/003 (duplicate pins, dead sphinx, 3 sources of truth).
5. **Config cluster:** 12-P0-002/P1-003/P1-004 (granian field dup, shutdown timeout, cgroup limits).

### 4.3 P2 — dead code / stub

Массовый слой; cleanup-уровень. Главные группы:
- DSL: 442 LOC dead `eip/reliability.py`, 11 P2 находок
- Security: 5× dead code paths (alias classes, hasattr-always-False, fire-and-forget audit)
- Workflow: 6× dead contracts/orphans
- Business Logic: 4× scaffold TODOs (Sprint 8+ не закрыт)

### 4.4 P3 — library replacement

Все 24 находки — concrete candidates с уже установленными mature alternatives:
- `tenacity` (audit, runners, MQ)
- `xmltodict` (DSL XML DRY)
- `faststream_fastapi` (entrypoints MQ)
- `presidio-analyzer` (PII)
- `rank_bm25` (RAG fallback)
- `OutboundHttpClient` facade (osint `_scrape_url`)

### 4.5 P4 — organic features

Mostly YAGNI-отложенные, отдельные organic.

---

## 5. Противоречия между cycle-2 отчётами (явные, не разрешались чтением source)

### 5.1 Layer-violations growth 173 → 180 — КОНСЕНСУС

**Единый вердикт 12 отчётов: реального роста НЕТ.**

- 175 legacy / 0 new = cycle-2 baseline (стабильно от cycle-1 baseline `b69d6b49`).
- `wc -l = 180` = 175 entries + 5 header-комментов.
- Формулировка «173→180» — метрический артефакт смешения `wc -l` и `grep -vE "^#|^$"`.
- Organic прирост в `[33→38]` циклов может объяснять +7 entries, но это **НЕ атрибуция роя cycle 2**.

### 5.2 Формулы readiness — несопоставимы

12 разных penalty-формул. Примеры:

- 01: `R = 100 - 35·P0 - 7·P1 - 3·P2 - 1·P3 + bounded_credit`
- 02: `R = 100 - 15·P0 - 8·P1 - 3·P2 - 1·P3` → 0 clamp + bounded_credit = 35
- 03: `R = 100 - 25·1 - 10·4 - 3·4 - 1·1 - 0.5·1 + 5 - 5 = 21.5 ≈ 22`
- 04: `R = 100 - 15·4 - 7·4 - 3·2 - 1·2 = 4`
- 05: `R = 100 - 20·5 - 10·3 - 4·2 - 2·1 = -40 → clamp 0`
- 06: `100 - 10·3 - 6·10 - 2·11 - 1·4 - 0.25·3 = -116.75 → 67 (capped rational)`
- 07: `100 - 20·5 - 10·3 - 4·6 - 2·3 - 1·3 = -163 → clamp 0`
- 08: `(80×0.40) + (0×0.30) + (50×0.20) + (70×0.10) = 49`
- 09: `100 - 25·1 - 10·1 - 2·2 - 1·1 - 1·1 = 59`
- 10: `100 - 18·4 - 10·2 - 4·4 - 1·2 = -10 → clamp 0`
- 11: `100 - 35·4 - 7·3 - 3·5 - 1·1 + bounded_credit = 30`
- 12: `100 - 25·2 - 10·2 - 3·3 - 1·3 - 0.5·2 = 17 → cap 79 → 47`

**Не разрешается:** формулы не масштабируются между доменами. Σ readiness ≠ среднее. Только как self-assessment каждого домена.

### 5.3 Resolved-Fix верификация — маскирующие mocks

- **08-P0-005 (LangGraph TypeError)**: fix logic есть в `process()` body, но tests mock `build_and_run_agent` через `AsyncMock` — баг не виден. **Conflict**: код «создан» но не работает.
- **09-P0-002 (RagCachePrewarmer silent no-op)**: tests mock `rag.query = AsyncMock(...)` — unit-tests «зелёные». **Conflict**: тесты маскируют runtime silent no-op (verified `Loaded: 0`).
- **08-P0-003 (hardcoded tenant_id)**: тесты mock `gateway = AsyncMock()` — финальный `AIRequest.tenant_id` не инспектируется. **Conflict**: lineage broken, тест не видит.
- **02-P0-003 (AuthValidateProcessor)**: test `test_handler_auth.py:60-64` mock'ит `_load_verifiers` — реальный runtime broken (`{}` возврат), но mock проходит.
- **06-P0-001 (ScanFile fail-open)**: test `test_scan_file_backend_unavailable_warn_mode_does_not_fail` PASS — фиксирует fail-open как design choice.

**Вывод:** 5 из 12 доменов подтверждают, что **unit-tests masking critical bugs** через mock. Cycle 3 должен включать integration-тесты без mock для этих 5+ paths.

### 5.4 Cycle-1 residuals — прямой cross-domain corroboration

**Verified RESIDUAL (cross-referenced между доменами):**

| Residual ID | Cross-domain corroboration |
|---|---|
| 02-P0-001 (validate_sql policy_override) | confirmed in 02 only; not echoed elsewhere |
| 02-P0-002 (deprecated auth_selector shim) | 02 only; 05 API report does NOT mention this shim |
| 04-P0-001 (SSE principal) | 04 only; 02 not mention SSE |
| 04-P0-002 (MQ DLQ) | 04 only; 01 infrastructure does NOT mention MQ subscribers |
| 05-P0-001/002/003/004 (admin/dsl mocks, hitl) | 05 only; 02 covers security but not admin endpoints |
| 10-P0-003/004 (credit/OSINT fail-open) | 10 only; unique to business logic |
| 06-DSL-P0-001 (scan_file fail-open) | 06 only |
| 06-DSL-P0-002 (XML XXE) | 06 only; **NOT** mentioned in 09 RAG (RAG не использует format_convert напрямую) |
| 11-DEPENDENCY-P0-001 (4-way CVE drift) | 11 only; 02 security не упоминает |

**Cycle-1 overridden by cycle-2 unawareness:**

- 02-P0-002 (auth_selector shim) — 5 prod consumers + 1 DSL + 2 tests, **но** 05 API report не включает этот shim в scope. Значит, fix должен включать миграцию файлов `entrypoints/middlewares/auth_required.py`, `entrypoints/webhook/handler.py`, `entrypoints/api/v1/endpoints/ai_stream.py`, `entrypoints/api/v1/endpoints/langmem_admin.py`, `entrypoints/api/v1/endpoints/ai_costs.py`, `dsl/engine/processors/security.py`.

### 5.5 Циклы cycle-1 residuals — формулировки и статусы

Все 12 отчётов явно пометили, что **cycle-1 отчёты не читали** (per task). Независимая cross-domain верификация:

- Cycle-1 Phase 4 закрыл: T-0.1, T-1.4, T-1.5, T-3.1 (по BASELINE.md).
- 02 security переоткрыл T-1.5 fix status как **RESOLVED** (verified working-tree).
- 06 DSL переоткрыл T-1.4 fix status как **RESOLVED** (multicast + redelivery_policy verified).
- 08 agents переоткрыл T-1.5 fix status как **двойной**: P0-001 (policy_mixin) и P0-002 (gateway_adapter) RESOLVED, но P0-003/004 (hardcoded tenant, fastmcp coupling) RESIDUAL.
- 05 API переоткрыл T-0.1 как **оставил mock-fallback** (RESIDUAL).
- 07 workflow, 09 RAG, 10 business logic, 11 dependencies, 12 settings-environment — все RESIDUAL'ы в их scope остаются.

**Конфликт:** `tools/cycle-1-preflight.sh` (упомянут в 11) — manual preflight gate, **не атрибутируется** рою cycle 2. Но это означает, что есть неинтегрированный инструмент из cycle 1.

### 5.6 Другие явные противоречия

1. **Cycle-1 layer-violations claim 173 vs cycle-2 BASELINE 175**: разница +2 entries, объясняется organic commits в `[33→38]`. Все 12 отчётов: «175 legacy / 0 new».
2. **Cycle-1 duplicate pins claim 9 vs cycle-2 verified 4**: 11-dependencies REFUTED-MUTATED. Расхождение объясняется тем, что 5 пакетов в single-pin (chromadb в mypy — config string, не pin).
3. **Cycle-1 8 undecorated processor families vs cycle-2 16 undecorated файлов/субпакетов**: 06 DSL — оба счёта отражают одну реальность (58 undecorated classes).
4. **MUST requirement ≥80 readiness**: 04 entrypoints (4), 05 API (0), 07 workflow (0), 10 business logic (0) — фактически 0-4 ≥ 80 impossible. 06 DSL (67), 08 agents (49), 09 RAG (59), 11 dependencies (30), 12 settings (47) — выше 0, но ниже 80. Только 01 infrastructure (45) и 02 security (35) — блок на P0.

### 5.7 Pending unresolved

**Нужна верификация разработчиком/архитектором:**

- 02-P0-004 (sync `AuthorizationGateway.check` bypasses OPA/Casbin): является ли это by-design или bug? sync path может быть только in-memory fallback? Docstring утверждает полный chain.
- 07-P0-001 (WorkflowFlags docstring lie): 4/5 flags default=True vs docstring "default-OFF" — это реальная фича, не regression. Возможно, legacy snapshots.
- 11-P0-002 (9 CVE already fixed in lockfile): подтверждается по `uv.lock`, но фактический `pip-audit` re-scan может изменить статус.
- 12-P0-002 (granian_tuning field dup): fix требует решения, какой field canonical — uvicorn (app_base) или granian (granian_tuning).
- 06-DSL-P0-001 (ScanFile fail-open): тест фиксирует fail-open как design choice. Возможно, нужен отдельный `on_backend_unavailable` param.
- 08-P0-006 (get_ai_agent_service NotImplementedError): composition root не регистрирует `app.state.ai_agent_service`. Это composition root bug, или extension plugins должны переопределять?

---

## 6. Кандидатный минимальный набор задач Phase 3 (зависимости и workstreams)

**Дизайн diff не делается (запрет на чтение source). Только организационная группировка и зависимости.**

### 6.1 Workstream A — Auth & Security Chain (broken + L5 migration)

**Findings (10):**
- 02-DOMAIN-P0-001, 02-DOMAIN-P0-002, 02-DOMAIN-P0-003, 02-DOMAIN-P0-004
- 04-DOMAIN-P0-001, 04-DOMAIN-P0-003, 04-DOMAIN-P0-004
- 05-API-P0-004, 05-API-P0-005
- 02-DOMAIN-P1-002 (SAML trust)

**Зависимости:** synchronous — все 10 должны коммититься atomарно с composition-root wiring.
**Effort estimate:** 10-15 LOC fix каждого, ~150-200 LOC total + composition wiring.
**Test criterion:** 8 SSE xfail → 0 xfail; 7 RAG endpoint pii xfail → 0 xfail.

### 6.2 Workstream B — Broken Imports / Production Crash (DI registry + agents)

**Findings (5):**
- 08-DOMAIN-P0-005 (LangGraph TypeError)
- 08-DOMAIN-P0-006 (get_ai_agent_service NotImplementedError)
- 10-DOMAIN-P0-001 (repos.files stale)
- 10-DOMAIN-P0-002/07-DOMAIN-WF-P0-005 (saga imports)
- 05-API-P0-003 (generator/setup.py broken)

**Зависимости:** composition root fix (08 P0-006) + DI provider mapping (10 P0-001) — должны идти вместе.
**Effort estimate:** 5-10 LOC fix каждого, ~50-80 LOC total.
**Test criterion:** runtime invocation `extensions/.../services/files.py::get_file_service()` возвращает рабочий instance.

### 6.3 Workstream C — Data Loss / DLQ (B-17 pattern application)

**Findings (4):**
- 01-DOMAIN-P0-001 (CDC DLQ writer failure)
- 04-DOMAIN-P0-002 (MQ subscribers ACK вместо DLQ)
- 03-DOMAIN-SVCS-P2-005 (audit DLQ priority-3 silent loss)
- 09-RAG-P0-002 (RagCachePrewarmer silent no-op) + 09-RAG-P0-004 (phantom fill_cache)

**Зависимости:** требует stable `DLQWriter` injection в MQ subscribers (новый DI provider).
**Effort estimate:** 30-50 LOC каждого, ~150-200 LOC total + new tests.
**Test criterion:** `test_subscribers_dlq.py` с mock `registry.dispatch = AsyncMock(side_effect=...)` → assert `dlq_writer.write` called once.

### 6.4 Workstream D — PII / Banking-Critical Fail-Open (extensions)

**Findings (4):**
- 10-DOMAIN-P0-003 (credit scoring fail-OPEN)
- 10-DOMAIN-P0-004 (OSINT report fabrication)
- 09-RAG-P0-001 (single-doc API PII bypass)
- 09-RAG-P0-003 (sanitizer exception fail-open)

**Зависимости:** extensions могут быть развёрнуты независимо друг от друга; banking-credit требует manual review с approval workflow.
**Effort estimate:** 5-15 LOC fix каждого, ~50 LOC total + extension test coverage.
**Test criterion:** `test_scoring_rejects_missing_income_or_amount` passes; `test_run_osint_fails_closed_on_llm_unavailable` passes.

### 6.5 Workstream E — Workflow Bootstrap + Saga Cleanup

**Findings (3):**
- 07-DOMAIN-WF-P0-005 / 10-DOMAIN-P0-002 (saga imports)
- 10-DOMAIN-P0-002 (orders_saga.py/payments_saga.py absent)
- 07-DOMAIN-WF-P0-001 (WorkflowFlags docstring lie)

**Зависимости:** либо восстановить saga модули, либо удалить `_bootstrap_default_declarations`. Второе проще.
**Effort estimate:** 30-50 LOC cleanup.
**Test criterion:** `tests/unit/plugins/composition/test_workflow_setup.py::test_bootstrap_with_flag_enabled` passes без ImportError.

### 6.6 Workstream F — Production-Startup Blockers (Settings-Environment)

**Findings (4):**
- 12-ENVSET-C2-P0-001 (Granian --shutdown-timeout invalid)
- 12-ENVSET-C2-P0-002 (graceful_shutdown_timeout dup field)
- 12-ENVSET-C2-P1-003 (hardcoded shutdown timeout=10)
- 07-DOMAIN-WF-P0-004 (TemporalWorkerPool never instantiated)

**Зависимости:** 12-P0-001 + 12-P0-002 — atomic (fix flag + одновременно mirror поле). 12-P1-003 + 07-P0-004 — независимо.
**Effort estimate:** 5-15 LOC каждого, ~50-80 LOC total.
**Test criterion:** `python tools/granian_runner.py --dry-run` exit 0; test `lifespan.run_shutdown()` use settings timeout.

### 6.7 Workstream G — DSL @processor Migration (cycle-38 B-04 closure)

**Findings (3):**
- 06-DSL-P1-009 (58 undecorated BaseProcessor classes)
- 06-DSL-P1-007 (audit.py no @processor)
- 06-DSL-P1-008 (scan_file.py no @processor)
- 07-DOMAIN-WF-P0-002 (4 workflow processors unregistered)

**Зависимости:** bulk-apply, low-risk (trivially bulk-применимо).
**Effort estimate:** ~50 LOC × 62 = 3100 LOC + schema/output/capability updates.
**Test criterion:** `len(get_processor_registry().list_by_namespace("core")) >= 65`.

### 6.8 Workstream H — CVE Drift / Security Gate (dependencies)

**Findings (4):**
- 11-DOMAIN-P0-001 (4-way CVE drift)
- 11-DOMAIN-P0-002 (9 CVE already fixed)
- 11-DOMAIN-P0-003 (pip_audit_gate IGNORED_VULNS hardcoded)
- 11-DOMAIN-P0-004 (streamlit open-ended)

**Зависимости:** atomic — single source of truth (file-allowlist → both gate + CI).
**Effort estimate:** 10-20 LOC каждого, ~50 LOC total.
**Test criterion:** `grep -E 'IGNORED_VULNS' tools/pip_audit_gate.py` → 0 hit; `make audit-deps` uses only file-allowlist.

### 6.9 Workstream I — Architecture Layer Cleanup (reverse-layer)

**Findings (5):**
- 01-DOMAIN-P1-001/002/003 (infra→services direct)
- 02-DOMAIN-P1-001 (DSL→entrypoints runtime importlib)
- 08-DOMAIN-P0-004 (DSL→infra fastmcp coupling)
- 10-DOMAIN-P1-001 (extension→infra dynamic import)

**Зависимости:** каждый — независимый fix в своём слое. Опционально: создать `core/ai/workflow_protocol.py` Protocol для 08-P0-004.
**Effort estimate:** 20-50 LOC каждого, ~200 LOC total + protocol/facade scaffolding.
**Test criterion:** `python tools/check_layers.py --root src` exit 0 + targeted layer test for each edge.

### 6.10 Workstream J — Dead Code Cleanup (P2/P3 bulk)

**Findings (массовый кластер):**
- 06 DSL: 11 P2 + 4 P3 (частично фасад reorganization)
- 03 Services: 4 P2 (QuotasService stub, 9× NotImplementedError placeholders, DLQPriority-3 silent loss)
- 07 Workflow: 6 P2 (4 contracts, ActivityBridge, TemporalWorkerPool)
- 02 Security: 5 P2 (alias classes, dead mixin attrs, etc.)
- 11 Dependencies: 4 P1 (4 duplicate pins de-dup)

**Зависимости:** bulk cleanup, low-risk.
**Effort estimate:** ~500-1000 LOC reduction.
**Test criterion:** `wc -l` уменьшается; smoke tests pass.

### 6.11 Граф зависимостей (high-level)

```
A (Auth) ─┐
B (Broken Imports) ─┤
C (DLQ) ─┤── Master Phase 3 sprint
D (PII/extensions) ─┤
E (Workflow) ─┤
F (Startup) ─┘
G (DSL @processor) ── independent
H (CVE) ── independent
I (Layer cleanup) ── dependencies: A (08-P0-004 needs L5 migration)
J (Dead code) ── independent (cleanup-pass)
```

**Потенциально независимые workstreams:** G, H, J (можно вести параллельно).
**Зависимые:** A + B (composition root), C + (composes with B), F + E (workflow-side).

---

## 7. Library replacement table

| Library | Cited custom code | Installed status (per reports) | Expected LOC reduction | License/maintenance evidence |
|---|---|---|---|---|
| `tenacity` (≥9.0.0,<10.0.0) | `core.resilience.retry.retry_async` (~50 LOC), `services/resilience/facade.py:205+`+ `with_retry`, `stream/invoker_subscribers.py:60-66` reconnect, `mqtt/mqtt_handler.py:128-129` hardcoded `asyncio.sleep(5)` | **Installed** (pyproject:74, used in 5+ files) | -50 to -100 LOC | NOT VERIFIED (per task: license/maintenance не проверялось) |
| `xmltodict` (≥0.14.0,<1.0.0) | 3× XML helpers duplication в `format_convert/{data_formats,encodings,specialized}.py:38-65` (108 LOC) | **Installed** (pyproject:96, 0.15.1) | -108 LOC | NOT VERIFIED (MIT, active maintenance — assumed) |
| `faststream_fastapi` (community) | `faststream.{rabbit,redis,kafka}.fastapi` imports (7 sites) | **NOT installed** (faststream 0.6.7 only) | -0 (drop-in) | NOT VERIFIED (Apache-2.0 upstream, community-maintained `faststream-community/faststream_fastapi` — risk medium) |
| `presidio-analyzer` | `core/security/pii_masker.py` regex-based (~200 LOC) | Referenced in `ai_policies/agent_basic.policy.yaml:31,38`; **NOT** verified in pyproject | -200 LOC if adopted | NOT VERIFIED (per 02: "проверить pyproject для presidio") |
| `rank_bm25` (≥0.2.2,<1.0.0) | `services/ai/hybrid_rag.py:196-210` manual token-overlap fallback (~13 LOC) | **Installed** (pyproject:124, 313) | -13 LOC | NOT VERIFIED (MIT, pure-Python BM25Okapi) |
| `OutboundHttpClient` facade | `extensions/osint_agent/.../osint_workflow.py:226-241` `_scrape_url` direct httpx | **Installed** (as net.outbound capability) | -20 LOC | NOT VERIFIED |
| `msgpack` (replaces pickle fallback) | `format_convert/data_formats.py:224-247` `_from_msgpack` pickle fallback | **NOT** verified (transitive dep at best) | -10 LOC | NOT VERIFIED (Apache-2.0) |
| `aio-pika` RobustConnection | `stream/invoker_subscribers.py` reconnect-логика | **Installed** (per pyproject:69) | -10..-20 LOC | NOT VERIFIED |
| `defusedxml` (≥0.7.1,<1.0.0) | `eip/marshal/formats.py:138-140` ET.fromstring fallback + `format_convert/...` ET.fromstring fallback | **NOT** direct dep (transitive via zeep) | -10 LOC + safer | NOT VERIFIED (Apache-2.0, defusedxml.org) |
| `polars` (already installed) | `eip/transformation.py:92-124` custom CSV split fallback | **Installed** (per pyproject, no fix) | -30 LOC | NOT VERIFIED (MIT) |
| `httpx` (replaces aiohttp) | `dsl/engine/processors/.../http_httpx.py` (already migrated) | **Installed** | 0 (already replaced) | NOT VERIFIED |
| `litellm` (already installed) | `agents_pydantic/adapter.py` LiteLLMModel — but `request_stream` NotImplementedError — пересекается с `core/ai/pydantic_ai_client.py:LiteLLMModelAdapter` (200+ LOC) | **Installed** | -200 LOC if deduplicated | NOT VERIFIED |
| `sqlalchemy` (already installed) | `core/repositories/base.py` abstract NotImplementedError (legitimate contract) | **Installed** | 0 (legitimate) | NOT VERIFIED |
| `tenacity` vs `tenacity.AsyncRetrying` | `services/audit/clickhouse_audit_service/service.py:268, 324` retry_async calls | **Installed** | -20 LOC if migrated | NOT VERIFIED |

**Не применимо / не проверено (per task):** полный maintenance/license audit `pip_audit_gate.py` upstream, `pip-audit` 2.10+ `--strict` flag, `pip-audit --requirement` allowlist support.

---

## 8. Organic feature table

| Feature | Benefit | Architecture fit | Evidence | Recommendation |
|---|---|---|---|---|
| Text-RAG E2E test (`tests/e2e/test_text_rag_e2e.py`) | Coverage пути `RAGService.augment_prompt → llm_call → response` | Соответствует E2E cycle 33 baseline (multimodal); augment mixin уже строит prompt string | Cycle-1 deferred (RAG-P4-001 confirmed RESIDUAL); `ls tests/e2e/` = multimodal only | **PLAN** (Phase 3 priority M): шаблон по `test_multimodal_rag_e2e.py` |
| BPMN subprocess multi-instance pattern (BPMN 2.0 §13) | Insurance/banking use-cases для claim-flow | Соответствует BPMN 2.0→WorkflowDeclaration import (уже работает) | `bpmn_importer.py` не покрывает multi-instance activity | **DEFER** (Phase 4/Sprint 8+) |
| Workflow timeout-cancellation через Temporal `workflow.new_timer` | Per-step TTL cancellation | Temporal Workflow API supports `asyncio.wait_for` + `cancel_after` pattern | `default_timeout_s` only на workflow level, не per-step | **DEFER** (low-priority, YAGNI) |
| Streaming response для `LiteLLMModel` | Полное соответствие pydantic_ai Model Protocol | `core/ai/pydantic_ai_client.py:LiteLLMModelAdapter` уже реализует через `_SimpleStreamedResponse` | Per 08: LiteLLMModel в agents_pydantic — NotImplementedError, нет extensions usage | **DEFER** (Ponytail: только если потребуется) |
| Saga pattern for orders (`extensions/core_entities/orders/workflows/orders_saga.py`) | Restore demo workflow | Соответствует `R-V15-9` workflow pattern | Удалён в commit `9164a59` (S168 W14), `tests/unit/workflows/test_orders_saga.py` skip | **DEFER** (либо удалить `_bootstrap_default_declarations`, либо восстановить) |
| Cellular algorithm-based ML scoring (замена `base_score=750` placeholder) | Banking-grade credit scoring | Заменяет rule-based P2-003 placeholder | `extensions/credit_pipeline/agents/__init__.py:74` explicit stub | **DEFER** (Phase 4) |
| Text-RAG → augment → LLM cycle (RAG-P4-001) | Production sign-off | EIP-augment pattern | `augment_mixin.py:AugmentMixin.augment_prompt` строит prompt string, без LLM call | **PLAN** (Phase 3) |
| `workflow_hooks.register_*` (banking/RPA/code-gen) | Future security surface | `core/ai/security/workflow_hooks.py:33-42` already defined | 0 production callers (только docstring example) | **DEFER** (YAGNI until banking use case) |
| List audit records ClickHouse fallback (DR scenario) | Disaster recovery | `services/audit/replay_query.py:30-90` только Redis stream | RAG-P4-001 analog; Redis stream может теряться | **DEFER** (Phase 4) |
| `credit_assessment.workflow.yaml` → real Temporal workflow | Production enablement | `extensions/credit_pipeline/workflows/*.yaml` declarative only | YAML не подключён к Temporal | **DEFER** (Sprint 8+) |
| `database_connection.py:284`/`external_databases/connection.py:177` `NotImplementedError` для Oracle RAC/PG-BDR | Расширение СУБД support | `core/config/database.py` validator | fail-loud design choice | **Document supported types** (P2-005 — settings report) |
| `tools/cycle-1-preflight.sh` integration | Make preflight part of regular CI | Manual preflight (35 active IDs check) | Не в `./github/workflows/` | **PLAN** (Phase 3) |
| Cache bus-based invalidation extension | Multi-tier cache consistency | `infrastructure/cache/rag/three_tier.py` already has bus | Per 02: working as designed | **Document** (no action) |
| `_run_granian` workers_kill_timeout parity | Granian deploy parity | `src/backend/main.py:81-117` SDK-based | `workers_kill_timeout` not propagated | **PLAN** (after fix 12-P0-002) |

---

## 9. Итог: какие P0/P1 блокируют порог ≥80 для каждого домена

### 9.1 Домены с readiness ≥ 80 (или близко) — НЕТ таких

Ни один домен не набрал ≥ 80. По самоотчётам:
- 06 DSL: 67 (ближайший)
- 09 RAG: 59
- 08 Agents: 49
- 12 Settings-Environment: 47 (cap 79)
- 01 Infrastructure: 45
- 02 Security: 35
- 11 Dependencies: 30
- 03 Services: 22
- 04 Entrypoints: 4
- 05 API: 0 (clamped)
- 07 Workflow: 0 (clamped)
- 10 Business Logic: 0 (clamped)

### 9.2 Какие P0/P1 блокируют ≥80 для каждого домена

**01 Infrastructure (45 → для ≥80 нужно +35):**
- Блокер: 01-DOMAIN-P0-001 (CDC DLQ writer failure), 01-DOMAIN-P1-001/002/003 (reverse-layer imports)
- Минимальный набор: workstream C (DLQ) + workstream I (layer cleanup)

**02 Security (35 → для ≥80 нужно +45):**
- Блокеры: 4 P0 + 3 P1 = 60 penalty (мощные)
- Минимальный набор: workstream A (auth/sync check fix) — закрыть 4 P0 = +60 score → 95

**03 Services (22 → для ≥80 нужно +58):**
- Блокеры: 1 P0 (AdminService fail-open) + 4 P1 (data_quality 5-way, shims, dead class)
- Минимальный набор: fix P0-001 (15 lines) + dedup P1-001 (120 LOC) + remove dead P1-004 (244 LOC) + cleanup shims (~50 LOC)

**04 Entrypoints (4 → для ≥80 нужно +76):**
- Блокеры: 4 P0 (SSE, MQ DLQ, CDC management, MQTT) + 4 P1 (parity)
- Минимальный набор: workstream A (auth) + workstream C (DLQ) — 4 P0 fixes (~80 LOC) + 4 P1 (~100 LOC)

**05 API (0 → для ≥80 нужно +80):**
- Блокеры: 5 P0 (admin mocks, broken import, hitl, mobile) + 3 P1 (admin_nats, admin_cron, invocations)
- Минимальный набор: 5 P0 fail-closed fixes (~50 LOC) + 3 P1 (~100 LOC)

**06 DSL (67 → для ≥80 нужно +13):**
- Блокеры: 3 P0 (ScanFile fail-open, XML XXE) + 10 P1 (undecorated, dup)
- Минимальный набор: 3 P0 fail-closed (~30 LOC) + decorator bulk-apply (workstream G)

**07 Workflow (0 → для ≥80 нужно +80):**
- Блокеры: 5 P0 (flags lie, 4 unregistered, ActivityBridge, TemporalWorkerPool, bootstrap saga)
- Минимальный набор: 5 P0 fixes (~200 LOC) + workstream E (workflow bootstrap)

**08 Agents (49 → для ≥80 нужно +31):**
- Блокеры: 4 P0 (LangGraph crash, get_ai_agent_service factory, hardcoded tenant, fastmcp coupling)
- Минимальный набор: workstream A (auth DSL→infra protocol) + workstream B (composition root)

**09 RAG (59 → для ≥80 нужно +21):**
- Блокеры: 4 P0 (PII fail-open, prewarmer silent fail, sanitizer fail-open, phantom fill_cache)
- Минимальный набор: 4 P0 fixes (~50 LOC) — biggest blocker: P0-001 require RagIngestService refactor

**10 Business Logic (0 → для ≥80 нужно +80):**
- Блокеры: 4 P0 (DI registry, saga imports, credit scoring, OSINT fabrication)
- Минимальный набор: 4 P0 fixes (~30 LOC) + new tests (~50 LOC) — high-priority banking

**11 Dependencies (30 → для ≥80 нужно +50):**
- Блокеры: 4 P0 (4-way drift, 9 CVE already fixed, hardcoded IGNORED_VULNS, streamlit open)
- Минимальный набор: workstream H (single source of truth for CVE) — ~50 LOC

**12 Settings-Environment (47 → для ≥80 нужно +33):**
- Блокеры: 2 P0 (Granian flag, dup field) + 2 P1 (shutdown timeout, cgroup limits)
- Минимальный на셋: workstream F (settings) — ~50 LOC

### 9.3 Cross-domain вклад

**Консолидированный находок P0 = 52, из них 10 имеют cross-domain corroboration** (1+ domain confirms):
- DLQ cluster: 01-P0-001/04-P0-002/03-SVCS-P2-005 (3 домена)
- Default brokers/broken registry: 10-P0-001/10-P0-002/07-P0-005 (3 домена)
- Architecture reverse-layer: 02-P1-001/08-P0-004/10-P1-001 (3 домена)
- Extension/migration: 02-P0-002 (5 consumers) + 05-P0-005 (mobile orphan) — overlap with 02 security

**Итого кросс-доменной работы (workstreams A-F):**
- ~700-1000 LOC fix
- ~30-50 new tests
- ~10-15 atomic commits

**Independent workstreams (G, H, J):**
- ~3000-4000 LOC cleanup
- ~20-30 commits
- Can be done parallel без blockers

---

## 10. Сводная таблица итогов

| Метрика | Значение |
|---|---|
| Всего findings (P0..P4) | **190** (52 P0, 49 P1, 51 P2, 24 P3, 14 P4) |
| Доменов с ≥3 P0 | 10 (01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12) |
| Доменов ≥80 readiness | **0** |
| Cross-domain corroborated P0 | 10+ (DLQ, broken imports, layer violations) |
| Workstreams (Phase 3 кандидаты) | 10 (A-J) |
| Independent workstreams | 3 (G, H, J) |
| Layer-violations growth 173→180 | **MYTH**: stable 175 legacy / 0 new; 180 = 5 header comments |
| Resolved cycle-1 P0 (verified) | 4 (T-0.1 partial, T-1.4, T-1.5 × 2) |
| Cycle-1 residuals (RESIDUAL) | 30+ (cross-domain verified) |
| Cycle-1 residuals (MUTATED) | 4 (P1-001 5-way, ENVSET-P1-003 k8s preStop, mobile_dead-code-isolated, DLQ priority-3) |
| Cycle-1 residuals (REFUTED) | 1 (cycle-1 "9 duplicate pins" → 4 actual) |
| Cycle-1 residuals (NOT VERIFIED) | Зависит от IDs, не сопоставлены (source offlimits) |
| Pending unresolved contradictions | 6 (05-P0-004 sync path, 07-P0-001 flags lie, 11-P0-002 9 CVE, 12-P0-002 field dup, 06-P0-001 scan_file, 08-P0-006 composition root) |
| Test-masking issues | 5+ (08-P0-005, 09-P0-002, 08-P0-003, 02-P0-003, 06-P0-001) |
| Pre-existing drift (not cycle-2) | `M uv.lock -15 svcs`, `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state` |
| Uncommitted cycle-1 Phase 4 source | 5 файлов (T-1.4/T-1.5/T-3.1) — ответственность developer commit step |

---

## 11. Финальные рекомендации (для родительского агента)

1. **Phase 3 priority — Workstreams A (auth) + B (broken imports) + D (PII/extensions)**: критический mass-fix (~30-40 LOC × 10 findings), atomic-коммиты в composition root + extensions. Effort: 4-6 dev-days.

2. **Workstreams C (DLQ) + E (saga) + F (startup)**: критический mass-fix инфраструктурных блокеров. Effort: 3-5 dev-days.

3. **Workstream G (DSL @processor) + H (CVE drift) + J (dead code)**: independent cleanup, можно disperse по потокам. Effort: 5-7 dev-days.

4. **Workstream I (Layer cleanup)**: можно распараллелить с A, B; effort 2-3 dev-days.

5. **Total Phase 3 estimate: 14-21 dev-days** для выхода на ≥80 across all 12 domains.

6. **Не разрешённые без source-read противоречия:** поручить архитектору (одна сессия 1-2 ч): 02-P0-004 sync path semantics, 07-P0-001 WorkflowFlags default, 11-P0-002 9 CVE carryover, 12-P0-002 field dup canonical, 06-P0-001 scan_file design, 08-P0-006 composition root registration.

7. **Test-masking issues (5+):** требуется integration-тесты без mock для runtime verification (resources: 1-2 dev-days).

8. **Pre-existing drift cleanup:** ответственность developer commit step (NOT к Phase 3).

---

**Phase 2 summarizer: завершён.** Отчёт сохранён в `docs/audit/swarm-2026-08-06/cycle-2/PHASE-2-SUMMARY.md`. Источники: 12 phase-1 отчётов + BASELINE.md. Без чтения source/git/cycle-1 отчётов. Без модификации файлов вне данного отчёта.
