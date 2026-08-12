# Cycle 3 — Phase 2 — Сводный summary по Phase 1

- **Дата:** 2026-08-06
- **HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (cycle retrospective commit)
- **Автор:** Phase 2 summarizer (read-only, никаких правок source/configs/lockfiles)
- **Источник:** только `docs/audit/swarm-2026-08-06/cycle-3/BASELINE.md` и
  `docs/audit/swarm-2026-08-06/cycle-3/phase-1/01..12-*.md`. Cycle-1/cycle-2 markdown,
  `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md` НЕ читались; любые прямые ссылки на эти
  источники помечены как «не проверено».

> **Предупреждение о методологии.** Аналитики использовали **разные формулы
> readiness** (домен services: 15·P0+8·P1+...; домен settings: 25·P0+10·P1+...;
> домен extensions: 100·passed/total − 5·P0 − 3·P1 − ...; домен workflow:
> 20·P0+8·P1+...). Поэтому scores **несопоставимы между доменами** и используются
> ниже **только как self-assessment** конкретного аналитика. Агрегировать
> scores в «overall» нельзя.

---

## 1. Executive summary и gate-status

### 1.1 Краткое резюме

12 независимых аналитиков Phase 1 исследовали свои домены **read-only** через
`.venv/bin/python -m pytest` (НЕ system Python, что было ошибкой reviewer cycle 2).
HEAD `7f3d94a3` — baseline-инварианты у всех совпадают:

| Baseline-инвариант | Значение | Источник |
|---|---:|---|
| Layer checker (new/legacy) | `0 / 175` (2274 файлов) | cycle-3 BASELINE + 01/05/06/10/11 подтвердили |
| Security allowlist | 35 active CVE/GHSA/PYSEC IDs | BASELINE + 02/11/12 подтвердили |
| Docstring gate | 0 missing (838 файлов) | BASELINE |
| Python interpreter | `.venv/bin/python` 3.14.0 | все 12 отчётов |
| Pre-existing drift | uv.lock −15 svcs, `pip-audit.json`, `.blue_green.state` | НЕ атрибутируется рою |

**Ключевая находка цикла 3:** cycle-1/cycle-2 фиксы **НЕ все дошли до production**;
многие «зелёные тесты» маскируют runtime-failures. 4 test-masking issues из cycle 2
PHASE-2 §5.3 **подтверждены в cycle 3** (см. §1.4).

**Critical findings (≥P0 data-loss/security/race/fail-open):** обнаружено
**~30 P0** в 11 из 12 доменов (домен «settings» имеет 0 новых P0 — все RESIDUAL
cycle-2). Основные категории:

1. **Composition root DI gaps** — `cdc`, `audit`, `admin` singletons не
   зарегистрированы как `dlq_writer_guard` (cross-domain corroboration: 01, 03,
   workflow — все отмечают одну и ту же категорию).
2. **Fail-open / silent data-loss** — OSINT (`raw_text=prompt` template),
   PII (`mask → return original text`), admin (`AuthZ unavailable → allow`),
   audit data-loss (`emit_capability_check` не awaited → coroutine GC'd).
3. **Test-masking** — `cycle 2 PHASE-2 §5.3` issues подтверждены в 5+ местах.
4. **Workflow Temporal lifecycle** — `bridge.decorate()` и `TemporalWorkerPool`
   не вызываются ни в одном production call-site; ADR-045 «Temporal = default»
   не реализован.
5. **Config / CVE drift** — 4-way enforcement разрыв между Makefile / GitHub
   workflow / GitLab CI / `pip_audit_gate.py`; 8 stale CVE в allowlist.

### 1.2 Gate-status по 12 доменам

| # | Домен | Readiness (self-assessment) | Cap-rule «≥80 запрещён при P0/P1» | P0 | P1 | P2 | P3 | P4 | Total | Блокирующие P0/P1 находки |
|---|---|---|:-:|--:|--:|--:|--:|--:|--:|---|
| 01 | infrastructure | 72 / 100 (raw=72) | cap=79 | 0 | 1 | 1 | 1 | 0 | 3 | test-infra sink/DLQ conftest не grants `dlq.write` (~40 failing tests) |
| 02 | security | 0 / 100 (clamped) | cap=79 | **3** | 2 | 1 | 2 | 1 | 9 | validate_sql drop, AuthValidateProcessor permanent fail-closed, capability audit data-loss |
| 03 | services | 0 / 100 (clamped) | cap=79 | **5** | 4 | 3 | 2 | 2 | 16 | TenantFacade TypeError, admin audit_callback unwired, audit DLQ unwired, PII fail-open, admin AuthZ fail-open |
| 04 | entrypoints | 0 / 100 (clamped) | cap=79 | **2** | 5 | 7 | 1 | 0 | 15 | SSE principal/permissions не пробрасываются (8 xfailed tests), MQ subscribers ACK vs DLQ (redelivery-loop) |
| 05 | api | 19 / 100 | cap=60 | **3** | 3 | 3 | 3 | 2 | 14 | HITL authz missing, admin_cron arbitrary RCE (`os:system` accepted), generator/setup.py broken import |
| 06 | dsl | 25.5 / 100 | cap=75 | **3** | 3 | 2 | 2 | 1 | 11 | ScanFile fail-open (RESIDUAL), XML XXE fallback (`_xml_to_dict_stdlib` billion-laughs подтверждён), WAF dotted-path semantic bug |
| 07 | workflow | 0 / 100 (floor) | cap=79 | **5** | 3 | 6 | 3 | 3 | 20 | Temporal-based path полностью сломан (ActivityBridge.decorate + TemporalWorkerPool не вызываются), WorkflowFlags docstring lie, 4 processors без `@processor`, cancel vs invoke sync semantics |
| 08 | agents | 20 / 100 (risk-adjusted) | <80 | **3** | 2 | 2 | 1 | 1 | 9 | AI service factory = `raise NotImplementedError` (зарегистрирован как `ai` getter), `AGENT_TOOL_POLICY_FAIL_OPEN`, gateway vs chat model split |
| 09 | rag | 24 / 100 | <80 | **4** | 2 | 2 | 2 | 2 | 12 | `_maybe_mask_pii` SystemExit bypass (production 500 на отсутствии spacy-model), RagCachePrewarmer broken (`RAGService` не имеет `.query()`), `get_rag_service` fallback dead code + missing module, multimodal E2E failing |
| 10 | business-logic | 79 / 100 | <80 (raw 78.8) | 1 | 2 | 7 | 2 | 1 | 13 | Dead saga imports (`extensions.{orders.workflows.orders_saga, payments_saga}` отсутствуют); OSINT fail-OPEN (banking) |
| 11 | dependencies | 35 / 100 | <80 | **3** | 2 | 2 | 2 | 0 | 9 | 8 stale CVE в active allowlist, `streamlit>=1.58.0` без upper bound, 4-way CVE drift между 4 enforcement точками |
| 12 | settings-environment | 65 / 100 | <80 | 0 new (4 RESIDUAL) | 2 | 4 | 2 | 1 | 9 | Hardcoded `task_registry.shutdown_all(timeout=10)` (k8s grace budget 30−15=15s), compose без CPU/memory limits (RESIDUAL cycle-2) |
| **Total** | 12 доменов | **несопоставимо** (разные формулы) | n/a | **29** | **28** | **38** | **22** | **13** | **130** | См. §3 |

> **Примечание.** Counts P0..P4 в колонках 8–12 — самосчёт аналитика; cross-check
> с §3 показывает, что **cross-domain corroboration** одного и того же root cause
> не уменьшает общий счётчик. Это сделано намеренно: каждый отчёт — самостоятельный
> witness.

### 1.3 Сводная карта готовности (visual)

```
Домен                   ≥80?     Cap-violating P0/P1
─────────────────────────────────────────────────────────────────
01 infrastructure        ✗       1 P1 (test-infra gap)
02 security              ✗       3 P0 + 2 P1
03 services              ✗       5 P0 + 4 P1
04 entrypoints           ✗       2 P0 + 5 P1
05 api                   ✗       3 P0 + 3 P1
06 dsl                   ✗       3 P0 + 3 P1
07 workflow              ✗       5 P0 + 3 P1
08 agents                ✗       3 P0 + 2 P1
09 rag                   ✗       4 P0 + 2 P1
10 business-logic        ✗       1 P0 + 2 P1
11 dependencies          ✗       3 P0 + 2 P1
12 settings              ✓       0 NEW P0/P1
```

**Вердикт:** **11 из 12 доменов** заблокированы P0/P1 против порога ≥80. Домен
`settings-environment` **не имеет новых P0/P1** (все его P0/P1 — RESIDUAL cycle-2),
но требует cleanup (RESIDUAL compose + hardcoded timeout).

### 1.4 Консенсус по 5+ test-masking issues из cycle 2 PHASE-2 §5.3

Cycle-2 PHASE-2 §5.3 зафиксировал наличие ≥5 test-masking проблем (см. BASELINE).
Cycle-3 **подтверждает** следующие (явный консенсус — см. §3 cross-domain register
для evidence из нескольких источников):

| # | Test-masking issue | Cycle-2 статус | Cycle-3 подтверждение | Источники в cycle-3 |
|---|---|---|---|---|
| TM-1 | MQ subscribers: `logger.error.assert_called()` без проверки ack/nack/DLQ handoff → masks infinite-redelivery-loop | CONFIRMED cycle 2 | **CONFIRMED** (entrypoints DOMAIN-P0-002; runtime подтверждено) | 04-entrypoints, 09-rag (RAG-P1-002 связан) |
| TM-2 | TenantFacade `test_with_tenant_restores_previous` — deselected/exit 1, masks TypeError | CONFIRMED cycle 2 | **CONFIRMED** (services DOMAIN-P0-001, `tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous` exit 1) | 03-services |
| TM-3 | DSL `_emit_audit` → coroutine `AuditService.emit` GC'd (1774 RuntimeWarnings) | CONFIRMED cycle 2 | **CONFIRMED** (security DOMAIN-P0-003; runtime warnings зафиксированы) | 02-security, 08-agents (parallel observation) |
| TM-4 | TemporalWorkerPool.register_worker тесты через AsyncMock-only, не поднимают реальный Worker | CONFIRMED cycle 2 | **CONFIRMED** (workflow DOMAIN-WF-P0-003+P0-004) | 07-workflow |
| TM-5 | Agent graph live LangGraph execution пропускается, маскируя kwargs mismatch | CONFIRMED cycle 2 | **CONFIRMED** (agents DOMAIN-P1-001) | 08-agents |

**Консенсус:** все 5 test-masking issues из cycle 2 PHASE-2 §5.3 **остаются в
силе в cycle 3**. Ни один из них не был фактически устранён — тесты продолжают
проходить, но маскируют runtime-failures. Это **главный структурный долг**,
который архитектор должен решить (см. §6 «Минимальный набор Фазы 3»).

Дополнительные test-masking кандидаты (открыты в cycle 3, **нужна верификация
разработчиком**):
- `tests/unit/infrastructure/database/test_smart_session_manager.py::test_read_routes_to_replica`
  (01-P3-NEW-001) — primary.calls=1 потому что lag-budget routing идёт через
  primary; тест написан до S19 W1.
- `tests/unit/dsl/eip/test_multicast_routes.py` (DSL-P2-002) — duplicate
  test-file с устаревшим `_engine_factory(*, route_registry=)` patch.
- `tests/unit/dsl/builders/test_eventbus_facade_wiring.py::test_handles_import_error`
  (06-P3 observed) — fixture drift (ищет `infrastructure_facade`, production
  использует `infrastructure_locator`).

---

## 2. Таблица всех 12 доменов (readiness + strengths + blockers + residuals + не проверено)

### 01 — Infrastructure

- **Readiness:** 72 / 100 (raw=72, cap=79). Блокирует P1.
- **Verified strengths (12):**
  1. Layer checker 175 legacy / 0 new (2274 файлов) — confirmed.
  2. T-3.1 cachetools.TTLCache — RESOLVED в working tree.
  3. B-17 CDC DLQ fail-loud — runtime-verified (13/13 tests PASS).
  4. CDC adapter 7/7 PASS.
  5. CompensatingDriverWorker 6/6 PASS.
  6. Cache infra 60/60 PASS.
  7. Resilience + observability 191/191 PASS.
  8. Messaging 28/28 PASS (без outbox/dlq).
  9. Storage 60/60 PASS (без s3.py — запрет).
  10. Sources 139/139 PASS + 2 skip.
  11. Composition root CDC wiring explicit + observable + idempotent.
  12. 35 active security IDs — стабильно.
- **Blockers:**
  - P1: `tests/unit/infrastructure/sinks/conftest.py` + `messaging/dlq/conftest.py`
    не grants `dlq.write` / `file.write` / `ws.send` / etc. для тестов с
    `@require_capability`-decorated sinks и DLQ writers (~40 failing tests).
  - P2: `compensating_driver.py:118` pure dead code (`repo = self._session_factory.__class__.__module__`).
  - P3: `test_smart_session_manager.py::test_read_routes_to_replica` test
    drift (primary.calls=1 из-за intentional lag-budget routing).
- **Cycle-1/2 residuals:**
  | ID | Статус | Док-во |
  |---|---|---|
  | T-3.1 cachetools | RESOLVED ✓ | git diff + 10/10 tests |
  | 01-P0-001 CDC DLQ | RESOLVED ✓ | B-02+B-17 wiring verified |
  | T-W1-04 composition DI | RESOLVED ✓ | = 01-P0-001 |
  | T-W2-01..04 layers | CONFIRMED ✓ | 175/0 |
  | T-W3-01 tenacity | PARTIAL | tenacity 9.0.0 installed, custom loop сохранён by-design |
  | 01-P1-001 test-infra | MUTATED → 01-P1-NEW-001 | та же root cause, переформулирована |
  | 01-P1-002..003 | UNVERIFIED | без cycle-2 markdown |
- **Не проверено:** `storage/s3.py` (запрет); `tenant_filter.py` (deprecated shim);
  outbox test failures (9 fails — pre-existing TypeError); eventing test
  failure (auth-message drift, last touch 6f28ff30).

### 02 — Security

- **Readiness:** 0 / 100 (clamped). Блокируют 3 P0 + 2 P1.
- **Verified strengths (10):**
  1. T-W1-01 RESOLVED — `AuthValidateProcessor` fail-closed verified.
  2. Cycle-2 P1-001..003 closed — capability + policy deny>allow.
  3. OPA runtime 14/14 tests pass.
  4. Cycle-2 dual-emit в CapabilityGate audit path.
  5. JWT weak-secret gate (RFC 7518 compliance).
  6. JWT blacklist: per-jti + batch revoke-before fail-closed.
  7. Auth middleware — defense-in-depth, pure ASGI.
  8. AuthorizationGateway deny-by-default (cycle-33 B-01).
  9. TLS CERT_NONE guard regression test (4 passed).
  10. YAML safe-load injection guard (4 passed).
- **Blockers:**
  - P0-001 RESIDUAL: `AgentSecurityFacade.validate_sql` silently drops
    `policy_override` (kwargs NEVER forwarded to framework, + framework
    `validate_sql` doesn't accept context).
  - P0-002 NEW: `AuthValidateProcessor` permanently fail-closed в production
    (`_VERIFIERS_MODULE = "entrypoints.api.dependencies.auth_selector"`, но
    shim удалил `_VERIFIERS` per S162 W5 → всегда `AuthenticationProviderUnavailableError`).
  - P0-003 NEW: Capability audit data-loss — `emit_capability_check(...)` в
    `audit_mixin.py:90` НЕ awaited → coroutine GC'd silently (1774 RuntimeWarnings).
  - P1-001 NEW: 6 hit `services/*` → `infrastructure/*` lazy imports
    (informational, layer-checker разрешает — backward-compat pattern).
  - P1-002 RESIDUAL: 5 entrypoints файлов импортируют deprecated shim
    `entrypoints.api.dependencies.auth_selector` (`auth_required.py:177`,
    `webhook/handler.py:38`, `ai_stream.py:27`, `langmem_admin.py:14`,
    `ai_costs.py:18`).
- **Cycle-1/2 residuals:**
  | ID | Статус | Док-во |
  |---|---|---|
  | DOMAIN-P0-001 (cycle-1) | RESIDUAL | runtime `inspect.getsource` confirmed |
  | DOMAIN-P0-002 (cycle-1) | RESIDUAL | runtime `hasattr(shim, '_VERIFIERS') = False` |
  | DOMAIN-P1-001..003 (cycle-2) | RESOLVED ✓ | S-02, S-03, S-04 |
  | T-W1-01 (cycle-2) | PARTIALLY RESOLVED | tests pass, runtime broken (см. P0-002) |
- **Не проверено:** cycle-1/cycle-2 markdown, `KNOWN_ISSUES.md`, 5 pre-existing
  failures в `test_gateway_pipeline_mixin.py` (вне scope).

### 03 — Services

- **Readiness:** 0 / 100 (clamped). Блокируют 5 P0 + 4 P1.
- **Verified strengths (16):** capability-checked facades (R174), tiered cache
  fallback, idempotency с явным fail-mode, async-first + `asyncio.to_thread`
  для CPU-bound (pytesseract), EIP-pattern processors, composition-root DI
  singleton pattern, resilience patterns (circuit breaker + retry), webhook
  relay Redis DLQ с fallback, schema-registry lock-free контракт,
  audit-replay в services (reverse-layer RESIDUAL fixed), reverse-layer shims
  (skb+files) корректные, ClickHouse DLQ unification, workflow audit через
  bulk-writer, PII-mask с audit-event, billing fail-mode явный,
  NotificationsFacade graceful degradation.
- **Blockers:**
  - P0-001: `TenantFacade.with_tenant` raises `TypeError: CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'` (runtime подтверждён).
  - P0-002: `services/admin/audit.py:60-62` + composition root — `set_audit_callback` нигде не вызывается → `emit_admin_action` молча no-op (compliance gap).
  - P0-003: `ClickHouseAuditService._send_to_dlq` silent_loss priority 3 + composition root не wire'ит `set_dlq_writer` для audit singleton (analog of B-17 для CDC).
  - P0-004: `PIIFacade.mask()` / `tokenize()` возвращают original text при exception — fail-OPEN на sensitive data (152-ФЗ, GDPR Art. 32).
  - P0-005: `AdminService._authorize` fail-OPEN при AuthZ unavailable.
  - P1-001: data_quality dataclasses 5-way duplication (`DQSeverity`,
    `DQViolation`, `DQCheckResult`, `DQRule` объявлены в 5 файлах →
    `id()` разные → `isinstance` cross-import сломано).
  - P1-002: data_quality check vs remediate inconsistency (`regex` vs `regex_match`, `allowed` vs `values`).
  - P1-003: 3 callers импортируют из `services.io.files` shim (DeprecationWarning spam).
  - P1-004: `CronDashboardService.get_success_rate` ambiguous 0.0 (неотличимо от no-data vs 100% failure).
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | T-2.1 reverse-layer cleanup | RESIDUAL (verified) — `services/audit/replay_query.py` перенесён, но `files.py` shim имеет 3 callers |
  | T-W1-04 composition root DI | RELATED → DOMAIN-P0-003 (audit singleton не wire'ит dlq_writer) |
  | T-W2-01..04 layer track | PARTIAL |
- **Не проверено:** полный код `jupyter/execution_service/e2b_backend.py`,
  `plugins/loader/loading/*`, конкретные lock-free гарантии schema-registry,
  реальные env-переменные.

### 04 — Entrypoints

- **Readiness:** 0 / 100 (clamped). Блокируют 2 P0 + 5 P1.
- **Verified strengths (12):** CDC + Filewatcher admin guard (T-W1-05 RESOLVED);
  GraphQL — gold standard principal/permissions; SOAP — partial parity; WS
  handshake auth; WebhookSignatureMiddleware fail-closed; WS handshake auth
  requirement (S172 M1.1); CDC DLQ-writer wiring (B-17 pattern);
  capability-checked facade layer; SSE PII-streaming через facade; Wave 1.5
  unified bridge; stream subscribers — happy path; WebhookSource parity.
- **Blockers:**
  - P0-001: SSE `/events/invoke` (`handler.py:188-246`) НЕ пробрасывает
    `principal`/`permissions` в `dispatch_action_or_dsl` → bridge получает
    defaults (`""`, `()`); 8 xfailed тестов в
    `test_handler_auth_propagation.py` (RESIDUAL cycle-1 T-1.2 / cycle-2
    T-W1-07).
  - P0-002: MQ subscribers (`stream/subscribers.py:33-50` +
    `invoker_subscribers.py:69-93`) `except Exception` → `logger.error` →
    нет `msg.ack()` / `msg.nack()` / DLQ handoff. Faststream default =
    infinite redelivery-loop. Tests mask: проверяют только
    `logger.error.assert_called()`.
  - P1-001: WS `/ws` и `/ws/invocations` authenticated, но не пробрасывают
    principal/permissions в `dispatch_action_or_dsl` / `invoker.invoke`.
  - P1-002: Inbound webhook (`webhook/handler.py:182-194`) — same.
  - P1-003: Express (BotX) `router.py:198-217` — same.
  - P1-004: gRPC `InvokerGRPCServicer.Invoke` + `auto_servicer.py:125-164` —
    не принимают principal из metadata / mTLS peer.
  - P1-005: GraphQL `schema.py:46-50` — 5 top-level `from src.backend.dsl`
    imports (тест ожидает 4) — pre-existing test failure (стилистика).
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | T-W1-05 (CDC+Filewatcher admin) | RESOLVED ✓ |
  | T-W1-03 (MQ subscribers) | RESIDUAL (= DOMAIN-P0-002) |
  | T-W1-07 (SSE principal) | RESIDUAL (= DOMAIN-P0-001) |
  | T-1.2 (cycle-1 SSE/HITL auth) | RESIDUAL |
  | T-1.3 (cycle-1 MQ DLQ data-loss) | RESIDUAL |
- **Не проверено:** `entrypoints/mcp/` полностью, `entrypoints/api/**` (вне scope),
  production-only smoke-test `mark_cdc_dlq_writer_wired`.

### 05 — API

- **Readiness:** 19 / 100. Блокируют 3 P0 + 3 P1.
- **Verified strengths (10):** AuthRequiredMiddleware defense-in-depth,
  22 admin_* endpoint-файла с `require_admin(...)`, CSRF/Rpa/PII/ai_tool
  middlewares, ActionRouterBuilder declarative, schemas/BaseSchema, HitlService
  async-first, login flow, ai_stream Depends(require_auth), 124 endpoint
  tests passed (9 xfailed RAG PII / AgentMemory tenant scope DEFER),
  21/21 mobile BFF tests passed.
- **Blockers:**
  - P0-001 RESIDUAL: HITL `hitl.py:24` router без Depends/auth guards —
    только global auth (DeprecationWarning, cross-tenant data leak, op
    integrity compromise).
  - P0-002 RESIDUAL ESCALATED: `admin_cron.py:86-94` `_resolve_callable` —
    Pydantic regex `^[\w.]+:[\w]+$` пускает `os:system`,
    `subprocess:check_output` без whitelist → admin OPERATOR может
    зарегистрировать arbitrary callable, RCE на cron tick.
  - P0-003 RESIDUAL: `generator/setup.py:12-14` broken import
    `src.backend.workflows.workflows_service` — модуль не существует
    (`find src/backend/workflows` пусто, директория удалена в S168 W12 P2-7).
    Тесты passes через `sys.modules` monkey-patch.
  - P1-001 RESIDUAL: `admin_nats.py:63-75` `importlib.import_module`
    bypasses layer-checker (entrypoints → infrastructure запрещён статически).
  - P1-002 NEW: `generator/setup.py` целиком — dead code, только тесты.
  - P1-003 NEW: `admin_cron.py:48-56` Pydantic regex — даже после RCE fix,
    любая admin role может регистрировать arbitrary callable без
    `_CRON_PUBLISHER` роли.
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | API-P0-001 (cycle-2) | RESIDUAL (= API-P0-001) |
  | API-P0-003 (cycle-2) | RESIDUAL (= API-P0-003) |
  | API-P0-004 (cycle-2) | RESIDUAL (= API-P0-001 HITL) |
  | API-P0-005 (cycle-2 Mobile BFF) | MUTATED P0→P2 (security concern → dead code concern) |
  | API-P1-010 (cycle-2) | ESCALATED → API-P0-002 |
  | API-P1-001 (cycle-2 admin_nats) | RESIDUAL (= API-P1-001) |
- **Не проверено:** cycle-1/cycle-2 markdown, `auth_selector`/`auth` dependencies
  beyond verified subset.

### 06 — DSL

- **Readiness:** 25.5 / 100 (cap 75 при P0/P1). Блокируют 3 P0 + 3 P1.
- **Verified strengths (6):** T-1.4 multicast + redelivery RESOLVED (15/15);
  EIP-маршрутизация 342/342; builders 510 passed, 1 failed
  (test-fixture drift eventbus); layer checker 175/0; документация/naming;
  XML-защита BPMN-импортёра (defusedxml).
- **Blockers:**
  - P0-001 RESIDUAL: `scan_file.py:78-120` `except Exception` +
    `on_threat='warn'` → exchange продолжается без AV скана
    (default `'fail'` fail-closed, но при `'warn'` opt-in — fail-open).
  - P0-002 RESIDUAL: `marshal/formats.py:139` fallback `ET.fromstring` при
    отсутствии defusedxml → billion-laughs DoS (dead path в prod,
    defusedxml 0.7.1 установлен).
  - P0-003 RESIDUAL: `format_convert/data_formats.py:61-66`
    `_xml_to_dict_stdlib()` → billion-laughs **active vuln in fallback**
    (196608 chars confirmed); дублируется в `encodings.py:63-66` +
    `specialized.py:61-64`.
  - P1-001 NEW: `idempotency.py:47-48` `IdempotentConsumerProcessor`
    Redis error → passes без dedup.
  - P1-002 NEW: `windowed_dedup.py:131-134, 303-306` `WindowedDedupProcessor`
    + `WindowedCollectProcessor` — same fail-open pattern.
  - P1-003 NEW: `waf_check.py:97-103` `source_property='foo.bar'` —
    читает body, не `body.foo.bar` (semantic bug, silent security miss).
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | DSL-P0-001 (cycle-2 scan_file AV) | RESIDUAL |
  | DSL-P0-002 (cycle-2 marshal XXE) | RESIDUAL (dead in prod) |
  | DSL-P0-003 (cycle-2 format_convert) | RESIDUAL + active in fallback |
  | DSL-P1-001..010 (cycle-2) | частично verified (3 candidates найдены) |
  | DSL-P2-001 (cycle-2) | NEW расширяет (XML helpers 3-way duplication) |
  | DSL-P3-001 (cycle-2) | verified в §4.2 DSL-P3-001 |
- **Не проверено:** `dsl/workflow/` compiler-логика полностью, `dsl/agents/`,
  `rag*` processors, `rpa/`, `ai/`, `telegram/*` (бизнес-callable methods).

### 07 — Workflow

- **Readiness:** 0 / 100 (floor). Блокируют 5 P0 + 3 P1.
- **Verified strengths (17):** WorkflowDeclaration Pydantic v2 schema,
  WorkflowBuilder fluent + 6 mixins, SagaBuilder + compensate_map validator,
  ActivityDeclaration capability tuple, compile_workflow dynamic Temporal
  class generation (B-15 fix), WorkflowCompilerRegistry, TemporalBackend
  Protocol 1:1, WorkflowHandle run_id валидация, await_completion typed
  mapping, DSLStepExecutor + DurableWorkflowRunner, CompensatingDriverWorker,
  YAML round-trip safe-only, BPMN importer XXE-safe, WorkflowLauncher
  SemVer resolution, WorkflowVersionRegistry strict-mode, HITL signal-store
  Redis, WorkflowAuditSink + cancel audit emit, Saga runner interrupt-safe.
- **Blockers:**
  - P0-001: `WorkflowFlags` docstring обещает "default-OFF" для 4 флагов,
    реальный default = `True` (config lie → silent operator surprise).
  - P0-002: 4 процессора без `@processor` декоратора
    (`workflow_convert.py`, `workflow_subprocess.py`,
    `best_practices/claim_check.py`, `best_practices/continue_as_new.py`) —
    YAML/builder `.workflow_*()` ломаются.
  - P0-003: `ActivityBridge.decorate()` нигде не вызывается → Temporal
    Worker `register_activity` упадёт с `AttributeError`.
  - P0-004: `TemporalWorkerPool` определён, но нигде не инстанцируется
    в production (только type hints). Temporal-based path полностью сломан.
  - P0-005: `cancel_workflow` пишет только в `result_property`,
    `invoke_workflow(mode=sync)` пишет и в body, и в property —
    inconsistent sync semantics.
  - P1-001: `invoke_workflow.py:143, 156` bare `except Exception` —
    swallowing версионных ошибок без лога.
  - P1-002: `cancel_workflow.py:146-148` `WorkflowHandle(workflow_id=wf_id, run_id=wf_id)` —
    Temporal различает workflow_id и run_id.
  - P1-003: `WorkflowHandle` Protocol vs Temporal handle semantics —
    cross-layer coupling размыт.
- **Cycle-1/2 residuals:** cycle-2 T-W1-02..04, T-W1-06..07, T-W2-01..04,
  T-W3-01, T-W4-01 — все НЕ ПРОВЕРЕНЫ (cycle-2 markdown запрещён); из
  контекста BASELINE: T-W3-01 tenacity library replacement RESOLVED
  (10-dependencies подтверждает).
- **Не проверено:** production runtime Temporal worker (нет live), workflow
  dynamic semantics, specific async contexts.

### 08 — Agents

- **Readiness:** 20 / 100 (risk-adjusted). Блокируют 3 P0 + 2 P1.
- **Verified strengths (8):** T-1.5 policy_mixin + gateway_adapter RESOLVED;
  agent policy tests 5/5; agent graph tool filtering fail-closed by default;
  process isolation default; agent security detector tests 29/29; agent DSL
  structural tests 39/39; agent registry TOML parsing; `build_and_run_agent`
  ai_gateway_enforce=True preflight.
- **Blockers:**
  - P0-001: `services/ai/ai_agent/__init__.py:109-111` `get_ai_agent_service()`
    безусловно raises `NotImplementedError`, но зарегистрирован как
    `"ai"` service и используется для `ai.search_web`, `ai.parse_webpage`,
    `ai.chat`, `ai.run_agent` → runtime fail.
  - P0-002: `agent_graph.py:307-319,327,335` `AGENT_TOOL_POLICY_FAIL_OPEN=true`
    deliberate fail-open security escape hatch (test explicitly proves).
  - P0-003: `ai_graph.py:180-196` `get_ai_gateway()` resolved but
    not passed to `build_chat_model`; line 199 passes independent
    `gateway` argument → split composition path.
  - P1-001: `ai_graph.py:220-221` `create_react_agent(max_iterations=10)` —
    `build_and_run_agent` не имеет `max_iterations` параметра (API mismatch,
    skipped live LangGraph test masks).
  - P1-002: `agent_sandbox.py:137-138` in-process sandbox audit emission
    catches every exception and silently `pass`es (security observability gap).
- **Cycle-1/2 residuals:** T-1.5 verified RESOLVED; P0-003..006, P1-001..004,
  P2-001..002, P3-001, P4-001 — exact prior evidence не проверено (no cycle-2
  markdown); current code does independently expose new blockers above.
- **Не проверено:** dependency license/maintenance metrics, LOC deltas for
  library replacement, live LangGraph runtime, exact cycle-2 finding text.

### 09 — RAG

- **Readiness:** 24 / 100. Блокируют 4 P0 + 2 P1.
- **Verified strengths (14):** `rag_service/__init__.py` корректный
  composition-root pattern; RAGService (4 mixin'а, 13 методов); tenant
  isolation (S2.6); embedding provenance (B3.5); source attribution (B3.3);
  ThreeTierRagCache facade; PII retrieval-mask opt-in; adaptive RAG
  strategy selection; EIP/Camel-like DSL integration; API via ActionRouterBuilder;
  RAGAS eval pipeline; ingest state store; chunker fingerprint;
  EmbeddingVectorCache via cachetools.TTLCache.
- **Blockers:**
  - P0-001: `rag_ingest_service.py:207-226` `_maybe_mask_pii` ловит только
    `Exception`, но `spacy.cli.download` → `SystemExit(1)` (BaseException)
    → bypasses catch → production 500 на каждом ingest при отсутствии
    `ru_core_news_lg`.
  - P0-002: `rag_cache_prewarmer.py:69,73` вызывает `self._rag.query(...)`,
    но `RAGService` **не имеет метода `.query()`** → runtime `AttributeError`
    → swallowed → `loaded=0` в production pre-warm.
  - P0-003: `rag_service/__init__.py:60-72` `get_rag_service` — wrapped-function
    fallback никогда не вызывается decorator'ом (decorator signature
    `app_state_singleton(attr, factory=)`); `InMemoryVectorStore` import —
    модуль НЕ существует.
  - P0-004: `tests/e2e/test_multimodal_rag_e2e.py:255-340` — 2/3 E2E-тестов
    FAILING (image/audio ingest без `tenant_id`, search с `tenant_id="e2e"`
    → filter mismatch → 0 hits). Pre-existing, не cycle-3 regression.
  - P1-001: `rag_query_stats.py:78-85` byte/str lookup — проверка типа
    первого ключа, не текущего → edge-case silent data-loss.
  - P1-002: `rag_ingest_service.py:118-140` `_run` loop — `except Exception`
    не ловит BaseException из `_maybe_mask_pii` → batch-ingest data-loss.
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | Cycle-2 RAG-P0-001 (PII fail-open) | VERIFIED RESIDUAL (= RAG-P0-001) |
  | Cycle-2 RAG-P0-002 (Prewarmer runtime) | VERIFIED RESIDUAL (= RAG-P0-002) |
  | Cycle-2 T-W4-01 (text-RAG E2E) | VERIFIED RESIDUAL (= RAG-P4-001) |
  | Cycle-1 T-4.1 (text-RAG E2E) | VERIFIED RESIDUAL (= RAG-P4-001) |
  | Cycle-2 P2-001 (chunker dead code) | MUTATED → RAG-P3-001 |
  | Cycle-2 P1-001 (layer violation) | MUTATED → no violation |
- **Не проверено:** `services/ai/rag/multimodal/` internals (только контекст для E2E),
  `services/ai/rag/{classifier,dense_retriever,...}`, agent layer, prod load.

### 10 — Business-logic (extensions/)

- **Readiness:** 79 / 100 (raw 78.8). Блокируют 1 P0 + 2 P1.
- **Verified strengths (7):** T-W1-08 credit scoring fail-closed RESOLVED
  (3/3 PASSED, full unit suite 13/13 PASSED); layer discipline (0 hits
  `from src.backend.{infrastructure,services,entrypoints}` в extensions/);
  plugin lifecycle hooks (35 tests PASSED); schemas-only extensions корректны;
  Pydantic валидация domain-моделей (4/4 PASSED); OSINT domain структура
  валидна (15/17 PASSED); banking helpers в core доступны.
- **Blockers:**
  - P0-001: `src/backend/plugins/composition/workflow_setup.py:76-82` —
    dead saga imports (`extensions.core_entities.orders.workflows.orders_saga`,
    `extensions.credit_pipeline.workflows.payments_saga`) — модули
    отсутствуют. Cross-scope blocker: cycle-2 P0-002 MUTATED.
  - P1-001: `extensions/osint_agent/functions/osint_workflow.py:306-313, 333-334`
    OSINT fail-OPEN на LLM-down — возвращает prompt template как "report"
    (banking-context risk, нет `data_source` маркера).
  - P1-002: `core/config/features/plugins.py:41-52` `credit_pipeline_v2`
    default=True противоречит description "default-OFF" и test-assertion
    (блокирует `test_credit_pipeline_v2_flag.py`).
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | T-1.1 composition root | VERIFIED OK в extensions scope (НЕ воспроизводится) |
  | T-2.1 reverse-layer cleanup | VERIFIED в extensions |
  | T-W1-08 credit scoring fail-closed | **VERIFIED RESOLVED** |
  | P0-002 (cycle-2 dead saga imports) | MUTATED → BL-P0-001 |
  | P0-004 (cycle-2 OSINT fail-OPEN) | RESIDUAL → BL-P1-001 |
- **Не проверено:** src/backend/** (вне scope), workflow runtime semantics
  (LiteTemporalBackend / Temporal), 5 pre-existing failures в
  `test_gateway_pipeline_mixin.py`.

### 11 — Dependencies

- **Readiness:** 35 / 100. Блокируют 3 P0 + 2 P1.
- **Verified strengths (4):** uv.lock + resolver (680 packages); 27+
  layer-aware extras; fail-closed security allowlist pipeline (35 active IDs,
  `make audit-deps` dynamic read); test-time runtime verification (51 passed).
- **Blockers:**
  - P0-001 RESIDUAL: 8 stale CVE IDs в active allowlist (installed ≥
    fix-version): `PYSEC-2026-161` (starlette 1.3.1 ≥ 1.0.1),
    `CVE-2026-46645` (sqladmin 0.30.0 ≥ 0.25.1), `CVE-2026-45739`
    (strawberry-graphql 0.323.2 ≥ 0.315.4), `GHSA-mv93-w799-cj2w`
    (gitpython 3.1.58 ≥ 3.1.50), `PYSEC-2026-142/141` (urllib3 2.7.0 ≥ 2.7.0),
    `CVE-2026-45409` (idna 3.18 ≥ 3.15), `PYSEC-2026-87` (lxml 6.1.1 ≥ 6.1.0).
  - P0-002 RESIDUAL: `pyproject.toml:137` `streamlit>=1.58.0` без upper bound
    (только это место в core deps).
  - P0-003 RESIDUAL: 4-way CVE drift между 4 enforcement точками —
    Makefile (35), GitHub workflow (2), GitLab CI (1), `pip_audit_gate.py`
    IGNORED_VULNS (1).
  - P1-001: `deptry` и `creosote` НЕ вызываются ни в одном
    `.github/workflows/*.yml` — drift в `testkit/` (moto, boto3 — DEP001)
    и `tools/` (clickhouse_connect — DEP001) не ловится в CI.
  - P1-002: `pip_audit_gate.py:18-21` stale comments —
    `PYSEC-2026-161 (starlette) FIXED in s30/w1` (false: всё ещё active),
    `CVE-2025-69872 (diskcache) REMOVED in s170` (false: diskcache 5.6.3
    всё ещё installed, JSONDisk cache не существует).
- **Cycle-1/2 residuals:**
  | ID | Статус |
  |---|---|
  | T-W3-01 (tenacity) | RESOLVED ✓ (tenacity 9.0.0+ pinned, 7+ import sites) |
  | P0-001 (cycle-2 4-way CVE drift + 9 CVE fixed) | RESIDUAL (= DEPS-P0-001+P0-003) |
  | P0-002 (cycle-2 hardcoded IGNORED_VULNS) | RESIDUAL (= DEPS-P1-002) |
  | P0-004 (cycle-2 streamlit no upper) | RESIDUAL (= DEPS-P0-002) |
- **Не проверено:** online `pip-audit` (PyPI JSON API timeout — network restricted);
  CycloneDX SBOM; cosign подписи; trivy/gitleaks/OWASP ZAP.

### 12 — Settings-Environment

- **Readiness:** 65 / 100 (raw 60 + 5 strengths). 0 NEW P0/P1.
- **Verified strengths (14):** STR-01 Granian CLI эмитит `--shutdown-timeout N`
  (cycle-2 P0-001 RESIDUAL FIXED); STR-02 Granian singleton runtime; STR-03
  multi-source loader; STR-04 fail-closed NotImplementedError; STR-05 debug_mode
  fail-closed; STR-06 hot-reload watcher; STR-07 Vault/Consul fail-silent; STR-08
  k8s+Helm resource limits; STR-09 ConfigValidator severity CRITICAL/WARNING;
  STR-10 35 active IDs; STR-11 438 settings tests passed; STR-12 granian_runner
  dry-run; STR-13 credit_pipeline fail-closed; STR-14 BaseSettingsWithLoader
  `extra="forbid"`.
- **Blockers (все RESIDUAL cycle-2):**
  - P0 RESIDUAL: compose без CPU/memory limits (5 compose-файлов, 0
    `deploy.resources.limits`, asymmetry с k8s+helm).
  - P0 RESIDUAL: hardcoded `task_registry.shutdown_all(timeout=10)` в
    `shutdown.py:199` (k8s grace budget 30−15=15s, hardcode съедает 2/3).
  - P0 MUTATED: Granian CLI flag (cycle-2 P0-001) — **FIXED** (6/6 tests).
  - P0 MUTATED: duplicate shutdown-timeout (cycle-2 P0-002) —
    PARTIAL (семантический dup остаётся, runtime-эффект отсутствует,
    uvicorn/granian mutually exclusive).
  - P1-001: Duplicate Granian config surface (`app_base.py:72-163` ↔
    `granian_tuning.py:43-225`), два runtime paths.
  - P1-002: `tools/config_audit.py:36` сканирует несуществующий
    `src/core/config/` вместо `src/backend/core/config/` — audit tool
    полностью нерабочий (pre-existing).
  - P2-001: Docstring hardcode `timeout=10` в `task_registry.py:17`.
  - P2-002: Bare `except Exception` в feature-flag lookup `granian_tuning.py:174`.
  - P2-003, P2-004: pre-existing test failures (НЕ cycle-3 swarm).
- **Cycle-1/2 residuals:** cycle-2 P0-001 (Granian CLI flag) MUTATED→FIXED;
  cycle-2 P0-002 (duplicate shutdown-timeout) MUTATED→PARTIAL;
  cycle-2 P0-003 (compose limits) RESIDUAL; cycle-2 P0-004 (hardcoded
  timeout) RESIDUAL.
- **Не проверено:** `.env`, `.env.*`, `secrets/**` (запрещены AGENTS.md),
  cycle-1/cycle-2 markdown, полный код scaling/* (только сигнатуры).

---

## 3. Нормализованный реестр findings P0→P4

> **Конвенция.** Глобальный ключ: `<domain>:<original-id>`. Source path/line
> и evidence взяты из соответствующего phase-1 отчёта. Cross-domain
> corroboration: одна и та же root cause упомянута в нескольких доменах —
> собраны источники, но **не дублированы** в общем счётчике.

### 3.1 P0 — security / data-loss / race / fail-open

| Global key | Original ID (per domain) | Original path:line | Status | Cross-domain corroboration |
|---|---|---|---|---|
| **security:DOMAIN-P0-001** | security:DOMAIN-P0-001 | `services/agent_security/facade.py:121-133` + `core/ai/security/agent_security.py:572-585` | RESIDUAL cycle-1 | — |
| **security:DOMAIN-P0-002** | security:DOMAIN-P0-002 | `dsl/engine/processors/security.py:52,55-89` | NEW (cycle-2 fix T-W1-01 закрыл только test, не runtime) | — |
| **security:DOMAIN-P0-003** | security:DOMAIN-P0-003 | `core/security/capabilities/gate/audit_mixin.py:88-99` | NEW (test-masking, см. TM-3) | agents (audit data-loss parallel observation, DOMAIN-P1-002 in-process sandbox `pass`) |
| **services:DOMAIN-P0-001** | services:DOMAIN-P0-001 | `services/tenancy/facade.py:116` | NEW | entrypoints (test-masking TM-2 cycle-2) |
| **services:DOMAIN-P0-002** | services:DOMAIN-P0-002 | `services/admin/audit.py:60-62` + composition root отсутствует | NEW | api (admin endpoints, security observability) |
| **services:DOMAIN-P0-003** | services:DOMAIN-P0-003 | `services/audit/clickhouse_audit_service/service.py:222-223` + composition root | NEW | infrastructure (B-17 cycle 37 CDC DLQ-wiring pattern — model for fix); workflow (T-W1-04 RELATED) |
| **services:DOMAIN-P0-004** | services:DOMAIN-P0-004 | `services/pii/facade.py:67-71, 96-101` | NEW (fail-open sensitive data) | — |
| **services:DOMAIN-P0-005** | services:DOMAIN-P0-005 | `services/admin/api.py:97-102` | NEW (fail-open) | — |
| **entrypoints:DOMAIN-P0-001** | entrypoints:DOMAIN-P0-001 | `entrypoints/sse/handler.py:188-246` | RESIDUAL cycle-1/cycle-2 | security (AuthValidateProcessor fails closed — different mechanism, same effect: principal not propagated) |
| **entrypoints:DOMAIN-P0-002** | entrypoints:DOMAIN-P0-002 | `entrypoints/stream/subscribers.py:33-50` + `invoker_subscribers.py:69-93` | RESIDUAL cycle-2 (T-W1-03) | infrastructure (B-17 DLQ-writer guard pattern для MQ); test-masking TM-1 cycle-2 |
| **api:API-P0-001** | api:API-P0-001 | `entrypoints/api/v1/endpoints/hitl.py:24` | RESIDUAL cycle-2 (API-P0-004) | entrypoints (SSE/HITL auth same root cause family) |
| **api:API-P0-002** | api:API-P0-002 | `entrypoints/api/v1/endpoints/admin_cron.py:86-94` | RESIDUAL cycle-2 ESCALATED P1→P0 | — |
| **api:API-P0-003** | api:API-P0-003 | `entrypoints/api/generator/setup.py:12-14` | RESIDUAL cycle-2 | — |
| **dsl:DSL-P0-001** | dsl:DSL-P0-001 | `dsl/engine/processors/scan_file.py:78-120` | RESIDUAL cycle-2 | — |
| **dsl:DSL-P0-002** | dsl:DSL-P0-002 | `dsl/engine/processors/eip/marshal/formats.py:139` | RESIDUAL cycle-2 (dead path in prod) | — |
| **dsl:DSL-P0-003** | dsl:DSL-P0-003 | `dsl/engine/processors/format_convert/data_formats.py:63` (+ duplicates) | RESIDUAL cycle-2 (active vuln in fallback) | — |
| **workflow:DOMAIN-WF-P0-001** | workflow:DOMAIN-WF-P0-001 | `core/config/features/workflow.py:32-72` | NEW (config lie) | — |
| **workflow:DOMAIN-WF-P0-002** | workflow:DOMAIN-WF-P0-002 | `dsl/engine/processors/workflow/{workflow_convert.py:23, workflow_subprocess.py:56, best_practices/claim_check.py:43, best_practices/continue_as_new.py:29}` | NEW | — |
| **workflow:DOMAIN-WF-P0-003** | workflow:DOMAIN-WF-P0-003 | `dsl/workflow/compiler/activity_bridge.py:288-305` | NEW (Temporal wiring broken) | workflow:DOMAIN-WF-P0-004 (TemporalWorkerPool never instantiated — same root cause family); test-masking TM-4 cycle-2 |
| **workflow:DOMAIN-WF-P0-004** | workflow:DOMAIN-WF-P0-004 | `infrastructure/workflow/temporal_client.py:227-321` | NEW | workflow:DOMAIN-WF-P0-003 |
| **workflow:DOMAIN-WF-P0-005** | workflow:DOMAIN-WF-P0-005 | `dsl/engine/processors/cancel_workflow.py:171-174` vs `invoke_workflow.py:213-214` | NEW | — |
| **agents:DOMAIN-P0-001** | agents:DOMAIN-P0-001 | `services/ai/ai_agent/__init__.py:109-111` | NEW (composition root gap) | workflow (T-W1-04 RELATED pattern) |
| **agents:DOMAIN-P0-002** | agents:DOMAIN-P0-002 | `dsl/engine/processors/agent_dsl/agent_graph.py:307-319,327,335` | NEW | — |
| **agents:DOMAIN-P0-003** | agents:DOMAIN-P0-003 | `services/ai/ai_graph.py:180-196` | NEW (gateway split) | — |
| **rag:RAG-P0-001** | rag:RAG-P0-001 | `services/ai/rag_ingest_service.py:207-226` | RESIDUAL cycle-2 | rag:RAG-P1-002 (BaseException bypass cascade) |
| **rag:RAG-P0-002** | rag:RAG-P0-002 | `services/ai/rag_cache_prewarmer.py:69,73` | RESIDUAL cycle-2 | — |
| **rag:RAG-P0-003** | rag:RAG-P0-003 | `services/ai/rag_service/__init__.py:60-72` | NEW | — |
| **rag:RAG-P0-004** | rag:RAG-P0-004 | `tests/e2e/test_multimodal_rag_e2e.py:255-340` | PRE-EXISTING (2/3 failing) | — |
| **business-logic:BL-P0-001** | business-logic:BL-P0-001 | `src/backend/plugins/composition/workflow_setup.py:76-82` | RESIDUAL cycle-2 MUTATED (dead imports в src + модули отсутствуют в extensions) | workflow (related saga DSL gap) |
| **dependencies:DEPS-P0-001** | dependencies:DEPS-P0-001 | `.security/pip-audit-allowlist.txt:65,67,69,71,74,76,79` | RESIDUAL cycle-2 | — |
| **dependencies:DEPS-P0-002** | dependencies:DEPS-P0-002 | `pyproject.toml:137` | RESIDUAL cycle-2 | — |
| **dependencies:DEPS-P0-003** | dependencies:DEPS-P0-003 | `.github/workflows/security.yml` vs `.gitlab/ci/.gitlab-ci.yml` vs `tools/pip_audit_gate.py` vs `make/security.mk` | RESIDUAL cycle-2 (4-way drift) | — |
| **settings:DOMAIN-P0-001** | settings:DOMAIN-P0-001 | `ops/compose/docker-compose*.yml` (5 файлов) | RESIDUAL cycle-2 | settings:DOMAIN-P4-001 (same root, downgraded для dev/staging) |
| **settings:DOMAIN-P0-002** | settings:DOMAIN-P0-002 | `src/backend/plugins/composition/lifecycle/shutdown.py:199` | RESIDUAL cycle-2 | settings:DOMAIN-P2-001 (duplicate hardcode в docstring) |
| **settings:DOMAIN-P0-003** | settings:DOMAIN-P0-003 | `src/backend/core/scaling/granian_tuning.py:222-223` | RESIDUAL cycle-2 → **FIXED** (cycle 3) | settings:DOMAIN-P0-004 (related) |
| **settings:DOMAIN-P0-004** | settings:DOMAIN-P0-004 | `app_base.py:115` + `granian_tuning.py:125` | RESIDUAL cycle-2 → MUTATED PARTIAL | settings:DOMAIN-P1-001 (overlap with Granian config surface) |

**Total P0:** 36 (incl. settings 4 RESIDUAL+2 mutated). Домен `infrastructure` — 0 P0.

### 3.2 P1 — architecture / layers / test-infra

| Global key | Original ID | Path:line | Status | Cross-domain |
|---|---|---|---|---|
| **infrastructure:01-P1-NEW-001** | infrastructure:01-P1-NEW-001 | `tests/unit/infrastructure/sinks/conftest.py:1-28` + 9 sinks + 3 dlq writers | NEW | (test infra gap, единственный P1 в infra) |
| **security:DOMAIN-P1-001** | security:DOMAIN-P1-001 | `services/{security,authorization}/*.py` + `services/auth/ad_directory_client/client.py` (lazy imports infrastructure) | NEW (informational, layer-checker permits) | — |
| **security:DOMAIN-P1-002** | security:DOMAIN-P1-002 | `entrypoints/{middlewares/auth_required.py:177, webhook/handler.py:38, api/v1/endpoints/{ai_stream:27, langmem_admin:14, ai_costs:18}}.py` | RESIDUAL cycle-1 (DOMAIN-P0-002) | — |
| **services:DOMAIN-P1-001** | services:DOMAIN-P1-001 | `services/ops/data_quality/{__init__.py, apply_mixin.py, check_mixin.py, schema_mixin.py, rule_mgmt_mixin.py}` | NEW (dataclass 5-way duplication) | — |
| **services:DOMAIN-P1-002** | services:DOMAIN-P1-002 | `services/ops/data_quality/check_mixin.py:80-160` vs `apply_mixin.py:370-401` | NEW (check vs remediate inconsistency) | — |
| **services:DOMAIN-P1-003** | services:DOMAIN-P1-003 | `src/backend/plugins/composition/service_setup.py:202`, `src/backend/dsl/commands/setup/registers_domains.py:70`, `src/backend/entrypoints/api/v1/endpoints/files.py:20` | NEW (3 callers из `services.io.files` shim) | business-logic:BL-P2-005 (related scaffold) |
| **services:DOMAIN-P1-004** | services:DOMAIN-P1-004 | `services/scheduler/cron_dashboard_service.py:110-137` | NEW | — |
| **entrypoints:DOMAIN-P1-001** | entrypoints:DOMAIN-P1-001 | `entrypoints/websocket/{ws_handler.py:286-294, ws_invocations.py:146-158}` | NEW (principal/permissions parity WS) | entrypoints:DOMAIN-P1-002..004 (parity pattern across transports) |
| **entrypoints:DOMAIN-P1-002** | entrypoints:DOMAIN-P1-002 | `entrypoints/webhook/handler.py:182-194` | NEW (parity webhook) | — |
| **entrypoints:DOMAIN-P1-003** | entrypoints:DOMAIN-P1-003 | `entrypoints/express/router.py:198-217` | NEW (parity Express) | — |
| **entrypoints:DOMAIN-P1-004** | entrypoints:DOMAIN-P1-004 | `entrypoints/grpc/grpc_server/invoker.py:105-124` + `grpc/auto_servicer.py:125-164` | NEW (parity gRPC) | — |
| **entrypoints:DOMAIN-P1-005** | entrypoints:DOMAIN-P1-005 | `entrypoints/graphql/schema.py:46-50` | NEW (5 imports vs expected 4) | — |
| **api:API-P1-001** | api:API-P1-001 | `entrypoints/api/v1/endpoints/admin_nats.py:63-75` | RESIDUAL cycle-2 | — |
| **api:API-P1-002** | api:API-P1-002 | `entrypoints/api/generator/setup.py` целиком | NEW (dead code) | api:API-P0-003 (related broken import) |
| **api:API-P1-003** | api:API-P1-003 | `entrypoints/api/v1/endpoints/admin_cron.py:48-56` | NEW (whitelist отсутствует) | api:API-P0-002 (same admin_cron scope) |
| **dsl:DSL-P1-001** | dsl:DSL-P1-001 | `dsl/engine/processors/eip/idempotency.py:47-48` | NEW (fail-open idempotency) | — |
| **dsl:DSL-P1-002** | dsl:DSL-P1-002 | `dsl/engine/processors/eip/windowed_dedup.py:131-134, 303-306` | NEW (fail-open dedup) | — |
| **dsl:DSL-P1-003** | dsl:DSL-P1-003 | `dsl/engine/processors/waf_check.py:97-103` | NEW (semantic bug) | — |
| **workflow:DOMAIN-WF-P1-001** | workflow:DOMAIN-WF-P1-001 | `dsl/engine/processors/invoke_workflow.py:143, 156` | NEW | — |
| **workflow:DOMAIN-WF-P1-002** | workflow:DOMAIN-WF-P1-002 | `dsl/engine/processors/cancel_workflow.py:146-148` | NEW | workflow:DOMAIN-WF-P1-003 (WorkflowHandle semantics) |
| **workflow:DOMAIN-WF-P1-003** | workflow:DOMAIN-WF-P1-003 | `core/workflow/backend.py:WorkflowHandle` | NEW (Protocol vs Temporal semantics) | — |
| **agents:DOMAIN-P1-001** | agents:DOMAIN-P1-001 | `services/ai/ai_graph.py:220-221` | NEW (API mismatch + test-masking) | test-masking TM-5 cycle-2 |
| **agents:DOMAIN-P1-002** | agents:DOMAIN-P1-002 | `services/ai/agent_sandbox.py:137-138` | NEW (in-process audit `pass`) | security:DOMAIN-P0-003 (parallel `emit_capability_check` not awaited) |
| **rag:RAG-P1-001** | rag:RAG-P1-001 | `services/ai/rag_query_stats.py:78-85` | NEW | — |
| **rag:RAG-P1-002** | rag:RAG-P1-002 | `services/ai/rag_ingest_service.py:118-140` | NEW (BaseException bypass cascade) | rag:RAG-P0-001 (cascade) |
| **business-logic:BL-P1-001** | business-logic:BL-P1-001 | `extensions/osint_agent/functions/osint_workflow.py:306-313, 333-334` | RESIDUAL cycle-2 (P0-004) | — |
| **business-logic:BL-P1-002** | business-logic:BL-P1-002 | `src/backend/core/config/features/plugins.py:41-52` | NEW (default vs description drift) | — |
| **dependencies:DEPS-P1-001** | dependencies:DEPS-P1-001 | `tools/checks/check_supply_chain.py:1-216` + workflows | NEW (deptry/creosote не в CI) | — |
| **dependencies:DEPS-P1-002** | dependencies:DEPS-P1-002 | `tools/pip_audit_gate.py:18-21` | RESIDUAL cycle-2 (stale comments) | dependencies:DEPS-P0-003 (same family 4-way drift) |
| **settings:DOMAIN-P1-001** | settings:DOMAIN-P1-001 | `app_base.py:72-163` ↔ `granian_tuning.py:43-225` | NEW (Gran config surface dup) | settings:DOMAIN-P0-004 (related) |
| **settings:DOMAIN-P1-002** | settings:DOMAIN-P1-002 | `tools/config_audit.py:36` | NEW (audit tool scans wrong path) | — |

**Total P1:** 30.

### 3.3 P2 — dead code / stubs / minor security hygiene

| Domain | Counts | Notable |
|---|---|---|
| infrastructure | 1 | compensating_driver.py:118 dead placeholder |
| security | 1 | JWT in-memory blacklist 24h clamped TTL |
| services | 3 | admin endpoints return []; QuotasService stub; DLQ silent_loss docstring |
| entrypoints | 7 | silent pass metrics, f-string+exc_info, system-source principal, faststream deprecation, IMAP/Scheduler/Filewatcher/MQTT |
| api | 3 | Mobile BFF dead code, versioning.py dead code, empty schema namespaces |
| dsl | 2 | XML helpers triplication, duplicate test file |
| workflow | 6 | ContinueAsNewHandler dead, run_workflow_by_id stub, stub docstrings, misleading name, docstring/code mismatch, WorkflowVersionRegistry без RLock |
| agents | 2 | AgentRegistry hot-reload scaffold; cleanup classification (DOMAIN-P2-002 = DOMAIN-P0-001 dual) |
| rag | 2 | dead `pass` statements в TYPE_CHECKING; pii_mask_on_ingest default-OFF + RAG-P0-001 cascade |
| business-logic | 7 | YAML reference broken, test fixtures stale, validate_inn None, dead dataclasses, scaffold __init__, layer-violation via importlib, noop compensation |
| dependencies | 2 | Sphinx requirements.txt deprecated; 7 deps без upper bound |
| settings | 4 | Docstring hardcode timeout, bare except, 2 pre-existing test failures |

**Total P2:** ~40 (точные counts: см. §1.2).

### 3.4 P3 — library replacement candidates / minor

| Domain | Counts | Notable |
|---|---|---|
| infrastructure | 1 | test_smart_session_manager lag-check test drift |
| security | 2 | `verify_signature` facade (no replacement); `_InMemoryJwtBlacklist` cachetools (already optimal) |
| services | 2 | `_apply_json_schema` → `Draft202012Validator.validate` (jsonschema installed); apprise (negative, no replacement) |
| entrypoints | 1 | узкий exception handling в MQ subscribers |
| api | 3 | auto_register tests, OpenAPI gaps, dynamic resolve_module |
| dsl | 2 | XML helpers consolidation; `_legacy.py` deprecation warning |
| workflow | 3 | DurableWorkflowRunner reimpl, SagaDeclaration validator duplication, `_exception_to_result` Temporal SDK overlap |
| agents | 1 | `StructuredTool` adapter (no replacement, negative) |
| rag | 2 | `chunk_text` → RecursiveChunker; NDCG@k non-standard |
| business-logic | 2 | INN validator library candidate; BaseExternalAPIClient/tenacity/httpx-retries |
| dependencies | 2 | deptry без config (289 issues); missing deps в tools/testkit |
| settings | 2 | pydantic-settings (already optimal); watchfiles (already optimal) |

**Total P3:** ~24.

### 3.5 P4 — organic features

| Domain | Counts | Notable |
|---|---|---|
| security | 1 | DSL `agent_security_policy` declarative override |
| services | 2 | (negative) 8 check types + 4 jupyter backends already exist |
| entrypoints | 0 | — |
| api | 2 | invocations OpenAPI idempotency-key; OpenAPI/AsyncAPI integration |
| dsl | 1 | recipient_list timeout per-step |
| workflow | 3 | cron/schedule DSL; parallel/fan-out; with_timeout per-step |
| agents | 1 | LangGraph session resume + durable checkpoint contract tests |
| rag | 2 | test_text_rag_e2e.py missing; multimodel_rag_enabled vs full flags merge |
| business-logic | 1 | real ML scoring (Sprint 8+ backlog) |
| dependencies | 0 | — |
| settings | 1 | compose resource limits (same as P0-001) |

**Total P4:** ~13.

### 3.6 Глобальная статистика

| Tier | Count | Notes |
|---|--:|---|
| **P0** | 36 | security/data-loss/race/fail-open; 11 доменов (все кроме infrastructure) |
| **P1** | 30 | architecture / layers / test-infra; 12 доменов |
| **P2** | ~40 | dead code / stubs / hygiene |
| **P3** | ~24 | library replacement (большинство negative) |
| **P4** | ~13 | organic features (большинство backlog) |
| **Total** | **~143** | Самостоятельные witness-счётчики per analyst. **НЕ агрегировать** (cross-domain corroboration не уменьшает counts) |

---

## 4. Приоритизация (по impact)

> Приоритеты **НЕ** по P0..P4 тегу, а по фактическому production impact.

### Tier A — Data-loss / Security gate / Race condition (блокеры sprint sign-off)

| # | Finding | Root cause | Affected surface |
|---|---|---|---|
| A1 | **services:DOMAIN-P0-001** (TenantFacade TypeError) | `CapabilityTenant.__init__(id, principal, scope_glob)` vs facade passes `tenant_id=` | All DSL processors using tenant-scoping |
| A2 | **services:DOMAIN-P0-002** (admin audit_callback unwired) | `set_audit_callback` grep = 0 hits in composition root | All admin actions: toggle_feature_flag, list_active_sessions, get_audit_log |
| A3 | **services:DOMAIN-P0-003** (audit DLQ unwired) | `audit_singleton.set_dlq_writer` grep = 0 hits; silent_loss path 3 in prod | ClickHouseAuditService on outage → silent loss |
| A4 | **services:DOMAIN-P0-004** (PII fail-open) | `mask()` returns original text on Exception | All PII-masked responses (banking, GDPR Art. 32, 152-ФЗ) |
| A5 | **services:DOMAIN-P0-005** (admin AuthZ fail-open) | `_authorize` returns on AuthZ unavailable | All admin endpoints (compliance gate) |
| A6 | **security:DOMAIN-P0-001** (validate_sql drop) | facade mutates kwargs but doesn't forward; framework doesn't accept context | Per-workflow SQL policy override (banking compliance) |
| A7 | **security:DOMAIN-P0-002** (AuthValidateProcessor permanent fail-closed) | `_VERIFIERS_MODULE` points to shim without `_VERIFIERS` | ALL DSL routes with `auth_validate: {methods: [jwt/api_key/saml/mtls]}` |
| A8 | **security:DOMAIN-P0-003** (capability audit data-loss) | `emit_capability_check` not awaited → coroutine GC'd | All capability-check audit events |
| A9 | **entrypoints:DOMAIN-P0-001** (SSE principal not propagated) | `dispatch_action_or_dsl` called without auth context | All SSE `/events/invoke` requests (8 xfailed tests) |
| A10 | **entrypoints:DOMAIN-P0-002** (MQ subscribers ACK vs DLQ) | `except Exception → logger.error` без ack/nack/DLQ | Redis Streams + RabbitMQ (infinite redelivery-loop risk) |
| A11 | **api:API-P0-001** (HITL authz missing) | `router = APIRouter()` без Depends | All HITL endpoints (cross-tenant data leak, op integrity compromise) |
| A12 | **api:API-P0-002** (admin_cron arbitrary RCE) | Pydantic regex пускает `os:system` | Admin OPERATOR can register arbitrary callable, RCE on cron tick |
| A13 | **workflow:DOMAIN-WF-P0-003** + **P0-004** (Temporal path completely broken) | `bridge.decorate()` + `TemporalWorkerPool` не инстанцируются | ALL Temporal-based workflows in production (ADR-045 promised Temporal = default) |
| A14 | **workflow:DOMAIN-WF-P0-001** (WorkflowFlags docstring lie) | 4 flags default=True but description "default-OFF" | Operator surprise → BPMN/gateway compiler half-baked code active by default |
| A15 | **workflow:DOMAIN-WF-P0-002** (4 processors без `@processor`) | DSL registration gap | YAML/builder `.workflow_convert()`/`.workflow_subprocess()`/`.workflow_claim_check()`/`.workflow_continue_as_new()` — KeyError на lookup |
| A16 | **agents:DOMAIN-P0-001** (AI service factory `raise NotImplementedError`) | `get_ai_agent_service` registered как `"ai"` getter | 4 registered AI actions (`ai.search_web`, `ai.parse_webpage`, `ai.chat`, `ai.run_agent`) — runtime fail |
| A17 | **agents:DOMAIN-P0-002** (`AGENT_TOOL_POLICY_FAIL_OPEN` escape hatch) | Environment override allows all tools when policy absent | All agent tool invocations (security escape hatch) |
| A18 | **agents:DOMAIN-P0-003** (gateway vs chat model split) | `get_ai_gateway()` resolved but not passed to `build_chat_model` | All LangGraph chat model constructions (enforcement bypass) |
| A19 | **rag:RAG-P0-001** (PII SystemExit bypass) | `_maybe_mask_pii` catches `Exception` but spacy raises `SystemExit` (BaseException) | Every ingest → HTTP 500 if `ru_core_news_lg` missing (default config) |
| A20 | **rag:RAG-P0-002** (RagCachePrewarmer runtime broken) | `RAGService.query()` doesn't exist; `RAGService` has `augment_prompt`, `search` | L2 semantic cache pre-warm on startup — silent `loaded=0` in prod |
| A21 | **rag:RAG-P0-003** (`get_rag_service` fallback dead + missing module) | `app_state_singleton(attr, factory=)` only calls factory; `InMemoryVectorStore` import → module not found | All unit-tests outside FastAPI context |
| A22 | **business-logic:BL-P0-001** (dead saga imports) | `extensions.{orders.workflows.orders_saga, credit_pipeline.workflows.payments_saga}` imports — modules don't exist | `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=true` → crash |
| A23 | **dependencies:DEPS-P0-001** (8 stale CVE в allowlist) | Installed ≥ fix-version, но CVE ID остался active | Real CVE может пройти незамеченным из-за noise |
| A24 | **dependencies:DEPS-P0-002** (streamlit без upper bound) | `streamlit>=1.58.0` — no `<2.0.0` | Streamlit 2.x breaking changes → 95 streamlit imports → runtime fail |
| A25 | **dependencies:DEPS-P0-003** (4-way CVE drift) | Makefile 35 / GH workflow 2 / GL CI 1 / gate 1 | GitLab CI fails on PR без ignore, GH passes; inconsistent enforcement |

### Tier B — Architecture / Layers / Fail-mode

| # | Finding | Impact |
|---|---|---|
| B1 | **infrastructure:01-P1-NEW-001** (test-infra sink/DLQ conftest) | ~40 failing tests; hides production fail-closed semantics |
| B2 | **api:API-P0-003** + **P1-002** (generator/setup.py broken + dead code) | Trap for future developers |
| B3 | **api:API-P1-001** (admin_nats importlib bypass) | Layer policy bypass через dynamic import |
| B4 | **dsl:DSL-P0-003** (`_xml_to_dict_stdlib` billion-laughs active in fallback) | Dead path in prod (xmltodict present), but latent vuln |
| B5 | **dsl:DSL-P1-003** (`waf_check` semantic bug) | `source_property='foo.bar'` читает body, не nested path |
| B6 | **entrypoints:DOMAIN-P1-001..004** (transport parity) | WS/Webhook/Express/gRPC — principal/permissions не пробрасываются |
| B7 | **services:DOMAIN-P1-001** + **P1-002** (data_quality dataclasses 5-way dup + check/remediate inconsistency) | Type-incompatibility risk; latent bugs |
| B8 | **services:DOMAIN-P1-003** (3 callers из shim) | DeprecationWarning spam |
| B9 | **services:DOMAIN-P1-004** (`CronDashboardService.get_success_rate` ambiguous 0.0) | Operator не различает no-data vs 100% failure |
| B10 | **security:DOMAIN-P1-002** (5 entrypoints импортируют deprecated shim) | DeprecationWarning каждый request к `/api/v1/ai_stream` etc. |
| B11 | **workflow:DOMAIN-WF-P0-005** (cancel vs invoke sync semantics) | Downstream `body` пустой при cancel |
| B12 | **workflow:DOMAIN-WF-P1-001..003** (silent exceptions + WorkflowHandle) | Diagnostics, Temporal/pg-runner mismatch |
| B13 | **agents:DOMAIN-P1-001** (`build_and_run_agent` kwargs mismatch) | Live LangGraph execution masked |
| B14 | **agents:DOMAIN-P1-002** (in-process sandbox audit `pass`) | Security observability gap |
| B15 | **rag:RAG-P1-001** (rag_query_stats byte/str lookup) | Redis mixed-mode silent data-loss |
| B16 | **rag:RAG-P1-002** (`_run` loop BaseException cascade) | Batch-ingest data-loss при одном PII-bad файле |
| B17 | **business-logic:BL-P1-001** (OSINT fail-OPEN) | Banking risk — prompt template как "report" |
| B18 | **business-logic:BL-P1-002** (credit_pipeline_v2 flag drift) | Test suite блокируется (`assert True is False`) |
| B19 | **settings:DOMAIN-P1-001** (Granian config surface dup) | Drift risk между app_base и granian_tuning |
| B20 | **settings:DOMAIN-P1-002** (`config_audit.py` scans wrong path) | Audit tool полностью нерабочий (pre-existing) |
| B21 | **dependencies:DEPS-P1-001** (deptry/creosote не в CI) | DEP001 drift в testkit/tools накапливается незаметно |
| B22 | **dependencies:DEPS-P1-002** (`pip_audit_gate.py` stale comments) | Misleading docs |

### Tier C — Dead code / Stubs / Cleanup

| Category | Examples |
|---|---|
| DSL/XML | DSL-P2-001 (XML helpers triplication), DSL-P2-002 (duplicate test file), DSL-P3-001 (consolidation) |
| DSL/legacy | DSL-P3-002 (`_legacy.py` deprecation), DSL-P4-001 (recipient_list timeout) |
| Workflow stubs | DOMAIN-WF-P2-001..006 (ContinueAsNewHandler dead, run_workflow_by_id stub, stub docstrings, misleading name, docstring/code mismatch, registry без RLock) |
| Agents stubs | DOMAIN-P2-001 (AgentRegistry hot-reload scaffold), DOMAIN-P2-002 (cleanup = DOMAIN-P0-001 dual) |
| RAG stubs | RAG-P2-001 (dead `pass`), RAG-P2-002 (pii_mask_on_ingest default-OFF cascade) |
| Extensions stubs | BL-P2-001..007 (YAML ref broken, test fixtures, validate_inn None, dead dataclasses, scaffold __init__, layer-violation via importlib, noop compensation) |
| Settings stubs | DOMAIN-P2-001 (docstring hardcode), DOMAIN-P2-002 (bare except), DOMAIN-P2-003/P2-004 (pre-existing test failures) |
| Deps cleanup | DEPS-P2-001 (Sphinx deprecated), DEPS-P2-002 (7 deps без upper), DEPS-P3-001 (deptry config), DEPS-P3-002 (moto/boto3) |
| Infra dead | 01-P2-NEW-001 (compensating_driver placeholder) |
| Services dead | DOMAIN-P2-001 (admin endpoints return []), DOMAIN-P2-002 (QuotasService stub), DOMAIN-P2-003 (DLQ silent_loss docstring) |
| API dead | API-P2-001 (Mobile BFF), API-P2-002 (versioning.py), API-P2-003 (empty schema namespaces) |

### Tier D — Library replacement / Organic features

См. §7 (Library replacement) и §8 (Organic features) — оба negative
(большинство уже optimal; replacements не рекомендуются).

### Tier E — Pre-existing не атрибутируется cycle 3

| Finding | Source |
|---|---|
| `services/ai/gateway_adapter.py:128-129` `except Exception: pass` | BASELINE (cycle-1 critic flagged) |
| 5 pre-existing failures в `test_gateway_pipeline_mixin.py` (spacy/feature flag) | BASELINE |
| uv.lock −15 svcs, `pip-audit.json`, `.blue_green.state` | BASELINE (pre-existing drift) |
| Pre-existing ruff I001+W292 в cycle-2 test files | BASELINE |
| Pre-existing ruff line-length `test_scoring_fail_closed.py:32` | BASELINE |
| `test_features_experimental.py::test_experimental_flags_instantiates` | settings DOMAIN-P2-003 |
| `test_hot_reload.py::test_start_disabled_in_prod` | settings DOMAIN-P2-004 |
| `test_credit_pipeline_v2_flag_exists_and_default_off` | business-logic BL-P1-002 |
| `test_valid_12_digit_inn` stale fixture, `test_none_inn` production bug | business-logic BL-P2-002/P2-003 |
| `test_mqtt_handler::test_defaults`, `test_stop_cancels_task` AsyncMock mismatch | entrypoints (pre-existing) |
| `test_extensions_layer_linter_clean` (3 NEW extensions violations) | infrastructure (out of scope) |
| `tests/unit/infrastructure/messaging/outbox/*` (9 fails — pre-existing TypeError) | infrastructure |
| `tests/unit/infrastructure/database/test_tenant_filter.py` (deprecated shim) | infrastructure |
| `tests/unit/infrastructure/eventing/test_inbox.py` (auth-message drift) | infrastructure |
| `tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py` (markdown content) | infrastructure |
| `tests/unit/infrastructure/database/test_smart_session_manager.py::test_read_routes_to_replica` (S19 W1 lag-check drift) | infrastructure 01-P3-NEW-001 |
| `tests/unit/infrastructure/security/test_vault_secrets.py::test_reauth_on_forbidden` | infrastructure |
| `tests/unit/infrastructure/clients/transport/test_http_no_circuit_breaker.py::TestLayerLinterNoRegression::test_extensions_layer_linter_clean` | infrastructure |
| `tests/unit/infrastructure/database/test_smart_session_manager.py::test_read_routes_to_replica` | infrastructure |
| 5 pre-existing failures в `test_gateway_pipeline_mixin.py` | settings pre-existing |

---

## 5. Противоречия между cycle-3 отчётами

> Явные конфликты, которые **не разрешаются** чтением source (запрещено
> инструкцией). Помечены «нужна верификация разработчиком/архитектором».

### C-1: System Python vs `.venv/bin/python` environment
**Конфликт:** reviewer cycle 2 принял `ModuleNotFoundError` за pre-existing
environment state; cycle 3 BASELINE + все 12 аналитиков подтверждают, что
`.venv/bin/python` имеет все нужные пакеты (`prometheus_client`, `fastapi`,
`hypothesis`), а system Python НЕ имеет. Reviewer использовал system Python
ошибочно.
**Разрешение:** BASELINE.md строка 10 + 12 отчётов (все использовали `.venv/bin/python`)
→ reviewer был неправ. Не влияет на findings.

### C-2: WorkflowFlags defaults vs descriptions
**Конфликт:**
- workflow (07): docstring обещает "default-OFF" для 4 флагов (`workflow_legacy_disabled`,
  `workflow_yaml_round_trip`, `workflow_bpmn_import`, `workflow_gateways_enabled`),
  реальный default = `True`. P0 finding.
- business-logic (10): `credit_pipeline_v2` default=True противоречит description
  "default-OFF" + test asserts default=False. P1 finding (test suite fails).
**Связь:** оба про **тот же antipattern** — Pydantic default не соответствует
description. Но разный severity, т.к. workflow flags влияют на BPMN/gateway
compiler (полуготовый код), а `credit_pipeline_v2` защищает legacy fallback
(skb.py уже real impl).
**Разрешение:** нужна верификация архитектором — какой template выбрать для
new feature flags (default=True или default=False)? Cycle 2 B-AUDIT предполагал
default=False, cycle 3 codebase показывает default=True. Conflict suggests
системного решения нет.

### C-3: test-masking TM-1 (MQ subscribers) — fault-mask severity
**Конфликт:**
- entrypoints (04) DOMAIN-P0-002: P0 fail-loud security/data-loss risk (infinite
  redelivery-loop).
- infrastructure (01): B-17 cycle 37 fix ВЫПОЛНЕН для CDC — DLQ-writer guard
  + composition wiring. Test-masking для CDC ЗАКРЫТ (13/13 PASS + real-runtime
  sanity).
**Связь:** MQ subscribers должны следовать B-17 pattern (DLQWriterGuard + DI),
но entrypoints (04) подтверждает, что pattern НЕ применён к MQ. Это разные
messaging surfaces; разный status.
**Разрешение:** нужна верификация, что cycle 3 не пропустил аналогичный
wiring для MQ subscribers вне scope entrypoints (messaging/). Из текущих
отчётов — **не подтверждено, что MQ wiring отсутствует полностью**, только
что entrypoints handlers `except Exception` без ack/nack/DLQ.

### C-4: Audit DLQ wiring — CDC vs ClickHouse
**Конфликт:**
- infrastructure (01) B-17: CDC DLQ-writer wired, 13/13 cycle-37 tests PASS,
  `cdc_dlq_writer_guard` exists.
- services (03) DOMAIN-P0-003: ClickHouse audit DLQ-writer **NOT wired** —
  composition root grep = 0 hits for `audit.*set_dlq_writer`. silent_loss
  path 3 in prod.
**Связь:** оба singleton services, оба имеют DLQ concept, разный status.
**Разрешение:** очевидно — services (03) находка валидна (composition root
должен повторить B-17 pattern для audit). Cycle 3 не воспроизводил
composition root в scope infrastructure, поэтому не видит этот gap.

### C-5: compose resource limits severity
**Конфликт:**
- settings (12) DOMAIN-P0-001: P0 (compose без CPU/memory limits).
- settings (12) DOMAIN-P4-001: P4 (same gap, downgraded до feature).
**Внутренний конфликт одного домена.** Self-priority drift.
**Разрешение:** нужна верификация — compose prod-критичный или dev-only?
settings (12) сам рекомендует downgrade до P3 если compose — только dev.
Финальная рекомендация: **downgrade до P3** (cosmetic, не блокер), т.к.
prod = k8s/helm (уже есть limits).

### C-6: data_quality dataclass scope
**Конфликт:**
- services (03) DOMAIN-P1-001: dataclass 5-way duplication — `id()` разные
  → `isinstance(v, DQViolation)` сломано для cross-import.
**Не conflict per se, но связан:**
- dsl (06) не отмечает data_quality; agents (08) не использует data_quality
  validators; workflow (07) использует saga DSL (forward+compensate), не
  DQ-validation.
**Связь:** Это **in-domain latent bug** (P1 в services), не cross-domain.
Но важно: type-incompatibility может сломать extension-ы, которые импортируют
DQViolation из другого модуля.
**Разрешение:** нужна верификация, какие extensions используют data_quality.

### C-7: OSINT fail-OPEN banking-context
**Конфликт:**
- business-logic (10) BL-P1-001: P1 — OSINT fail-OPEN на LLM-down,
  banking-context risk. Cycle 2 P0-004 → cycle 3 RESIDUAL.
- security (02): НЕ отмечает OSINT отдельно; AI safety policy в
  `agent_basic.yaml` + `credit_check_strict.yaml` НЕ упоминает OSINT.
**Связь:** OSINT вызывается из credit_pipeline (banking), но security
domain не проводит аудит extension OSINT. Blind spot.
**Разрешение:** нужна верификация архитектором — нужен ли cross-extension
audit для банковских use cases? AGENTS.md упоминает "extensions/<name>/"
как business logic, но security P0 должны покрывать banking-context.

### C-8: Workflow Temporal lifecycle vs pg_runner
**Конфликт:**
- workflow (07) DOMAIN-WF-P0-003+P0-004: Temporal path полностью сломан,
  ADR-045 promised Temporal = default.
- workflow (07) Strengths: DSLStepExecutor + DurableWorkflowRunner (pg-runner
  backend) работает корректно.
- workflow (07) Conclusion: "Production-ready только для pg_runner backend".
**Связь:** ADR-045 vs reality. Cycle 3 не разрешает, какой backend production.
**Разрешение:** нужна верификация архитектором — является ли Temporal
production target? Если да, P0-003+P0-004 блокеры. Если pg_runner is
production, то Temporal = YAGNI (P3 remove, как cycle 2 P0-005 решение
для `DOMAIN-WF-P3-001` library replacement).

### C-9: dsl/engine/processors/scan_file fail-open default
**Конфликт:**
- dsl (06) DSL-P0-001: P0 RESIDUAL — `on_threat='warn'` mode = fail-open
  (default `'fail'` = fail-closed).
- services (03): нет соответствующего finding (scanner не в scope services).
- security (02): нет finding для AV scanner (нет in-scope virus scanning
  module).
**Связь:** Разный security posture по умолчанию в разных domains.
**Разрешение:** нужна верификация — какой default для `on_threat` рекомендуется?
Cycle 3 код: `on_threat='fail'` (fail-closed). DSL-P0-001 рекомендация —
документировать operational risk.

### C-10: Cycle 2 / T-W3-01 (tenacity) — VERIFIED vs PARTIAL
**Конфликт:**
- infrastructure (01) T-W3-01: PARTIAL — tenacity 9.0.0 installed,
  custom loop сохранён by-design в outbox dispatcher.
- dependencies (11) §1.1 + §3 verified: RESOLVED ✓ — `tenacity>=9.0.0,<10.0.0`,
  7+ import sites, installed 9.1.4.
**Связь:** оба правы, но scope разный:
- dependencies: package installed and pinned.
- infrastructure: outbox dispatcher использует custom exponential backoff
  **by design** (per-attempt state preservation), не кандидат на замену.
**Разрешение:** НЕТ конфликта. T-W3-01 закрыт для большинства use-cases,
но outbox dispatcher остаётся by-design custom. RESIDUAL в узком смысле.

### C-11: Pre-existing test failures vs Cycle 3 attribution
**Конфликт:**
- BASELINE.md line 32-39: список pre-existing failures (5 в `test_gateway_pipeline_mixin.py`,
  1 ruff, 1 line-length, 9 outbox, 4 tenant_filter, 2 inbox, 4 cdc_status_docs,
  1 smart_session_manager test_read_routes_to_replica).
- Разные cycle-3 аналитики:
  - 02-security: 5 fails в `test_gateway_pipeline_mixin.py` НЕ его scope.
  - 01-infrastructure: те же fails НЕ его scope (но listed 01-P3-NEW-001).
  - 12-settings: 2 pre-existing (DOMAIN-P2-003, P2-004) НЕ этому swarm.
- BASELINE line 5: "14 modified files (cycle-1 uncommitted: 5 source + 4 test + 1 preflight;
  cycle-2 uncommitted: 4 source + 2 test + 1 audit doc)" — НЕ атрибутируются
  рою cycle 3.
**Разрешение:** нужно developer commit step перед cycle 3 → cycle 4 attribution.
Cycle 3 swarm НЕ должен их ровнить.

### C-12: Workflow registry naming
**Конфликт:**
- workflow (07) §5.2: 3 разных registry с похожими именами (`WorkflowRegistry`,
  `WorkflowDescriptorRegistry`, `WorkflowCompilerRegistry`). Naming collision.
- infrastructure (01): `cache/rag/embedding_cache.py` уже использует
  `cachetools.TTLCache` (cycle 1/T-3.1 RESOLVED) — naming convention OK.
**Связь:** Cognitive load vs cross-domain consistency.
**Разрешение:** нужна верификация архитектором — целесообразен ли rename
в `WorkflowDescriptorRegistry` (workflow §5.2 рекомендация).

### C-13: SAGAS imports vs orders_dsl
**Конфликт:**
- business-logic (10) BL-P0-001: `extensions.{orders.workflows.orders_saga,
  credit_pipeline.workflows.payments_saga}` отсутствуют в extensions/.
- workflow (07) §2 strengths: `extensions/core_entities/orders/workflows/orders_dsl.py`
  — saga DSL через `WorkflowBuilder().saga().forward().compensate()` —
  5 workflows.
**Связь:** extensions/core_entities/orders использует `orders_dsl.py`, не
`orders_saga.py`. Composition root импортирует `orders_saga` (dead), но
`orders_dsl` содержит реальные saga builders.
**Разрешение:** нужна верификация архитектором — обновить composition root
import на `orders_dsl.build_all_order_workflows()` или удалить dead imports.

### C-14: `_InMemoryJwtBlacklist` TTL limit
**Конфликт:**
- security (02) DOMAIN-P2-001: P2 — `_InMemoryJwtBlacklist.ttl=86400` fixed,
  long-lived service-tokens (> 24h) теряются.
- security (02) DOMAIN-P3-002: P3 (informational) — cachetools already optimal.
**Внутренний конфликт одного домена:** P2 vs P3 для одного и того же кода.
**Разрешение:** нужна верификация — насколько real risk? Production = Redis
backend (`_create_jwt_blacklist` line 79-103), in-memory = fallback. Если
fallback активен только в dev → P3. Если in prod → P2.

### C-15: agent graph tool filtering default
**Конфликт:**
- agents (08) Strength #3: "Agent graph tool filtering is fail-closed by default"
  (verified by `test_no_policy_fail_open_via_env`).
- agents (08) DOMAIN-P0-002: `AGENT_TOOL_POLICY_FAIL_OPEN=true` deliberate
  fail-open — test explicitly proves.
**Связь:** Default = fail-closed, environment override = fail-open. Спор —
является ли environment override «intentional opt-in» (strength) или
«security escape hatch» (P0)?
**Разрешение:** нужна верификация — production config rejects
`AGENT_TOOL_POLICY_FAIL_OPEN`? Если нет — P0 валиден. Если да — P3.

---

## 6. Кандидатный минимальный набор задач Фазы 3

> **Группировка** по atomic fix unit. Dependencies отмечены явно. Independent
> workstreams отмечены явно. **Не проектирую diff вместо архитектора** —
> только work-breakdown и приоритизация.

### Workstream WS-1: Composition Root DI (высокая связанность)

**Atomic fixes (все требуют правок в `src/backend/plugins/composition/`):**

| ID | Fix | Deps | Notes |
|---|---|---|---|
| WS-1.1 | **services:DOMAIN-P0-003** Audit DLQ-wiring — добавить `audit_singleton.set_dlq_writer(inbox_dlq_writer)` в composition root + создать `_audit_dlq_writer_guard.py` по аналогии с `cdc_dlq_writer_guard.py` | **Инвариант:** WS-1.2 (CDC DLQ pattern reference) | Cross-domain (infrastructure + services) |
| WS-1.2 | **services:DOMAIN-P0-002** Admin `set_audit_callback` wiring в composition root | None | NEW composition wiring |
| WS-1.3 | **agents:DOMAIN-P0-001** AI service factory — заменить placeholder `raise NotImplementedError` на canonical DI slot или singleton factory | None | Composition root gap |
| WS-1.4 | **business-logic:BL-P0-001** Dead saga imports — либо удалить блок `from extensions....saga import`, либо создать extension stubs | None | Cross-domain (workflow + business-logic) |
| WS-1.5 | **workflow:DOMAIN-WF-P0-003** + **P0-004** Temporal Worker lifecycle — создать `infrastructure/workflow/worker_runtime.py` с инстанциацией `TemporalWorkerPool` + `ActivityBridge.decorate()` | ADR-045 verification (разработчик) | HIGH effort, HIGH risk |
| WS-1.6 | **api:API-P1-001** admin_nats importlib bypass — перенести `nats_metrics.py` из `infrastructure/observability/` в `services/observability/` + статический import | None | Cleanup |

**Independent workstream:** все WS-1.* затрагивают composition root, можно
объединить в один Sprint 37 fix-wave.

### Workstream WS-2: Fail-open / Silent data-loss (data integrity)

| ID | Fix | Deps |
|---|---|---|
| WS-2.1 | **services:DOMAIN-P0-004** PII mask fail-open → `raise PIIMaskError` или marker return | None |
| WS-2.2 | **services:DOMAIN-P0-005** Admin `_authorize` fail-open → `raise AdminAuthorizationError` | None |
| WS-2.3 | **services:DOMAIN-P0-001** TenantFacade `with_tenant` kwargs fix (id=..., principal=...) | None |
| WS-2.4 | **security:DOMAIN-P0-001** validate_sql — facade пробрасывает context + framework принимает policy_override | None |
| WS-2.5 | **security:DOMAIN-P0-002** AuthValidateProcessor `_VERIFIERS_MODULE` → `core.auth.auth_selector` (canonical) | None |
| WS-2.6 | **security:DOMAIN-P0-003** Capability audit data-loss → `_emit_audit` async + `await emit_capability_check(...)` | None |
| WS-2.7 | **api:API-P0-001** HITL authz — добавить `Depends(require_permission("hitl.resolve"))` + tenant context filtering | None |
| WS-2.8 | **api:API-P0-002** admin_cron RCE — добавить `ALLOWED_CALLABLE_PREFIXES` whitelist + `_CRON_PUBLISHER` роль | None |
| WS-2.9 | **rag:RAG-P0-001** + **RAG-P1-002** `_maybe_mask_pii` `except Exception` → `except (Exception, SystemExit)` + fallback на `AIDataSanitizer.legacy` | None (связано с rag:RAG-P1-002 cascade) |
| WS-2.10 | **business-logic:BL-P1-001** OSINT fail-OPEN — `report["data_source"] = "real"/"fallback"/"empty"` + raise на полный fallback | None |

**Independent workstream:** 10 atomic fixes, ~6-8h effort суммарно.

### Workstream WS-3: Test-masking (5+ issues, structural)

> **Эти fixes должны быть сделаны подряд, иначе regression coverage остаётся
> фиктивной.**

| ID | Fix | Deps |
|---|---|---|
| WS-3.1 | **TM-1** MQ subscribers ACK vs DLQ — добавить DLQWriterGuard для MQ (по аналогии с CDC) + test assertions на `msg.ack()` called + DLQ message published | None |
| WS-3.2 | **TM-2** TenantFacade — `tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous` — fix capability kwargs + re-enable test | WS-2.3 |
| WS-3.3 | **TM-3** DSL `_emit_audit` coroutine — добавить test `test_audit_mixin_does_not_drop_coroutine` + AsyncMock-based assertion на awaited | WS-2.6 |
| WS-3.4 | **TM-4** TemporalWorkerPool — добавить integration test с `WorkflowEnvironment.start_local()` | WS-1.5 |
| WS-3.5 | **TM-5** Agent graph live LangGraph — добавить runtime test с LangGraph installed | None (требует pyproject установки) |
| WS-3.6 | **rag:RAG-P0-004** Multimodal E2E — fix test (ingest с `tenant_id="e2e"`) | None |
| WS-3.7 | **dsl:DSL-P2-002** Delete duplicate `tests/unit/dsl/eip/test_multicast_routes.py` | None |
| WS-3.8 | **infra:01-P3-NEW-001** smart_session_manager — `monkeypatch.setattr(sm, "_update_lag_status", AsyncMock())` | None |

**Independent workstream:** каждый test-masking fix самостоятелен; рекомендуется
батч WS-3.1 + WS-3.2 + WS-3.3 + WS-3.7 в один PR, WS-3.4 отдельно.

### Workstream WS-4: Workflow DSL registration + Temporal wiring

| ID | Fix | Deps |
|---|---|---|
| WS-4.1 | **workflow:DOMAIN-WF-P0-002** Добавить `@processor(...)` к 4 классам (`workflow_convert`, `workflow_subprocess`, `workflow_claim_check`, `workflow_continue_as_new`) | None |
| WS-4.2 | **workflow:DOMAIN-WF-P0-001** `WorkflowFlags` defaults → `False` + обновить descriptions | None |
| WS-4.3 | **workflow:DOMAIN-WF-P0-005** `cancel_workflow` добавить `exchange.set_out(...)` | None |
| WS-4.4 | **workflow:DOMAIN-WF-P1-001** `invoke_workflow.py` типизированные exception catches + логирование | None |
| WS-4.5 | **workflow:DOMAIN-WF-P1-002** `cancel_workflow` принять optional `run_id` параметр | None |

**Independent workstream:** atomic, ~2-3h effort суммарно.

### Workstream WS-5: Settings / Config / CVE

| ID | Fix | Deps |
|---|---|---|
| WS-5.1 | **dependencies:DEPS-P0-001** Удалить 8 stale CVE из `.security/pip-audit-allowlist.txt` (L65, 67, 69, 71, 74, 76, 79) + `IGNORED_VULNS` PYSEC-2026-87 из `tools/pip_audit_gate.py` | None |
| WS-5.2 | **dependencies:DEPS-P0-002** `pyproject.toml:137` `streamlit>=1.58.0,<2.0.0` | None |
| WS-5.3 | **dependencies:DEPS-P0-003** Unify 4 CVE enforcement sites на `.security/pip-audit-allowlist.txt` (Makefile pattern) | WS-5.1 |
| WS-5.4 | **dependencies:DEPS-P1-001** Add `deptry` job to `.github/workflows/lint.yml` (non-blocking) | None |
| WS-5.5 | **dependencies:DEPS-P1-002** Удалить L18-21 stale comments в `pip_audit_gate.py` | None |
| WS-5.6 | **settings:DOMAIN-P0-002** `shutdown.py:199` параметризовать `timeout` через `settings.app.graceful_shutdown_timeout` | None |
| WS-5.7 | **settings:DOMAIN-P0-001** Compose `deploy.resources.limits` (или downgrade до P3, см. C-5) | None |
| WS-5.8 | **settings:DOMAIN-P1-001** Консолидировать Granian config surface | None |
| WS-5.9 | **settings:DOMAIN-P1-002** `tools/config_audit.py:36` — `CONFIG_DIR = ROOT / "src" / "backend" / "core" / "config"` (1-line fix) | None |

**Independent workstream:** WS-5.1 → WS-5.3 (зависимость); WS-5.6, WS-5.7, WS-5.8
можно делать независимо.

### Workstream WS-6: Library replacement / Minor (Tier D)

| ID | Fix | Deps |
|---|---|---|
| WS-6.1 | **infrastructure:01-P1-NEW-001** Test-infra sink/DLQ conftest — autouse fixture grants `dlq.write`/`file.write`/etc. для тестов | None (HIGH impact, ~40 failing tests) |
| WS-6.2 | **services:DOMAIN-P3-001** `_apply_json_schema` → `Draft202012Validator.validate` (jsonschema 4.26.0 уже installed) | None |
| WS-6.3 | **services:DOMAIN-P1-001** Data_quality dataclasses → `_types.py` consolidation | None |
| WS-6.4 | **services:DOMAIN-P1-002** Data_quality check vs remediate unification | WS-6.3 |
| WS-6.5 | **services:DOMAIN-P1-003** Migrate 3 callers из `services.io.files` shim → `extensions.core_entities.files.services.files` | None |
| WS-6.6 | **services:DOMAIN-P1-004** `CronDashboardService.get_success_rate` — return `Optional[float]` или tuple | None |
| WS-6.7 | **dsl:DSL-P0-003** `_xml_to_dict_stdlib` → defusedxml drop-in (или удалить функцию) | None |
| WS-6.8 | **dsl:DSL-P1-001..002** `IdempotentConsumerProcessor`, `WindowedDedupProcessor` — `fail_closed: bool = True` parameter | None |
| WS-6.9 | **dsl:DSL-P1-003** `waf_check.py:97-103` — always resolve dotted-path | None |
| WS-6.10 | **infrastructure:01-P2-NEW-001** Удалить `compensating_driver.py:118` dead placeholder | None |
| WS-6.11 | **api:API-P0-003** Удалить `setup.py` + `test_setup.py` (dead code, broken import) | None |
| WS-6.12 | **api:API-P2-001..003** Удалить Mobile BFF / versioning.py / schema namespaces | None |

**Independent workstream:** каждый фикс самостоятелен; батчами по домену.

### Workstream WS-7: Agent DSL / RAG cleanup

| ID | Fix | Deps |
|---|---|---|
| WS-7.1 | **agents:DOMAIN-P0-002** Remove/restrict `AGENT_TOOL_POLICY_FAIL_OPEN` в production | None |
| WS-7.2 | **agents:DOMAIN-P0-003** Pass resolved gateway to `build_chat_model` (или unified contract) | None |
| WS-7.3 | **agents:DOMAIN-P1-001** Fix `langgraph_agent.py:74-78` kwargs (`query=...` → `prompt=...`, `max_iterations=...` → supported recursion limit) | None |
| WS-7.4 | **agents:DOMAIN-P1-002** Repair in-process sandbox audit coroutine handling | None |
| WS-7.5 | **agents:DOMAIN-P2-001** Remove or implement AgentRegistry hot reload | None |
| WS-7.6 | **rag:RAG-P0-002** Replace `rag.query()` → `rag.augment_prompt()` (или удалить `RagCachePrewarmer` как dead code) | None |
| WS-7.7 | **rag:RAG-P0-003** Replace wrapped-function fallback на `factory=_default_rag_service_factory` + создать `core/vector_store/memory.py:InMemoryVectorStore` | None |
| WS-7.8 | **rag:RAG-P1-001** Fix rag_query_stats byte/str lookup | None |
| WS-7.9 | **rag:RAG-P3-001** Replace custom `chunk_text` → `RecursiveChunker` из `services/ai/chunkers/` | None |
| WS-7.10 | **rag:RAG-P4-001** Create `tests/e2e/test_text_rag_e2e.py` | None |

### Workstream WS-8: API + Transport parity

| ID | Fix | Deps |
|---|---|---|
| WS-8.1 | **entrypoints:DOMAIN-P0-001** SSE `/events/invoke` principal/permissions propagation (8 xfailed tests) | None |
| WS-8.2 | **entrypoints:DOMAIN-P1-001..004** WS/Webhook/Express/gRPC — same propagation | None |
| WS-8.3 | **entrypoints:DOMAIN-P1-005** GraphQL 5 imports — accept as S168 W11 P2-4 decision | None |
| WS-8.4 | **entrypoints:DOMAIN-P3-001** MQ subscribers `except Exception` + warning log | None |
| WS-8.5 | **api:API-P3-001** Auto_register tests fix (правильная iteration через nested routes) | None |
| WS-8.6 | **api:API-P3-002** Auto_register `response_model` + dynamic `body_model` | None |
| WS-8.7 | **api:API-P1-002** Delete `generator/setup.py` (dead code) | None |
| WS-8.8 | **api:API-P1-003** Add `_CRON_PUBLISHER` role | WS-2.8 |

### Workstream WS-9: Extensions cleanup

| ID | Fix | Deps |
|---|---|---|
| WS-9.1 | **business-logic:BL-P1-002** `credit_pipeline_v2` default consistency (False or update doc/test) | None |
| WS-9.2 | **business-logic:BL-P2-001** Workflow YAML references — delete or stub `fetch_for_workflow` / `emit_decision` | None |
| WS-9.3 | **business-logic:BL-P2-002** Replace stale test fixture "770708389307" → valid INN12 | None |
| WS-9.4 | **business-logic:BL-P2-003** `validate_inn(None)` guard | None |
| WS-9.5 | **business-logic:BL-P2-004** Delete `CompanyInfo` + `OsintReport` dead dataclasses | None |
| WS-9.6 | **business-logic:BL-P2-005** Clean 4 scaffold-only `__init__.py` | None |
| WS-9.7 | **business-logic:BL-P2-006** Replace lazy `_S3_MOD` с capability facade | None |

### Workstream WS-10: Pre-existing test fixes (developer commit step)

| ID | Fix | Notes |
|---|---|---|
| WS-10.1 | `test_features_experimental.py::test_experimental_flags_instantiates` | settings DOMAIN-P2-003, **NOT cycle-3 swarm** |
| WS-10.2 | `test_hot_reload.py::test_start_disabled_in_prod` | settings DOMAIN-P2-004 |
| WS-10.3 | `test_credit_pipeline_v2_flag_exists_and_default_off` | business-logic BL-P1-002 |
| WS-10.4 | `test_valid_12_digit_inn`, `test_none_inn` | business-logic BL-P2-002/P2-003 |
| WS-10.5 | `test_mqtt_handler::test_defaults`, `test_stop_cancels_task` | entrypoints (pre-existing) |
| WS-10.6 | 5 failures в `test_gateway_pipeline_mixin.py` (spacy/feature flag) | BASELINE — не атрибутируется cycle 3 |
| WS-10.7 | 9 outbox test failures (`TypeError: lambda takes 0 positional arguments`) | BASELINE — pre-existing |
| WS-10.8 | 4 tenant_filter test failures (deprecated shim) | BASELINE — pre-existing |
| WS-10.9 | 2 inbox test failures (auth-message drift, last touch 6f28ff30) | BASELINE — pre-existing |
| WS-10.10 | 4 cdc_status_docs failures (markdown content) | BASELINE — pre-existing |
| WS-10.11 | 1 `test_vault_secrets.py::test_reauth_on_forbidden` | BASELINE — pre-existing |
| WS-10.12 | 1 `test_http_no_circuit_breaker.py::test_extensions_layer_linter_clean` | BASELINE — pre-existing |
| WS-10.13 | Pre-existing ruff I001+W292 в cycle-2 test files | BASELINE — auto-fixable |
| WS-10.14 | Pre-existing ruff line-length `test_scoring_fail_closed.py:32` | BASELINE — auto-fixable |

### Independent workstreams (можно запускать параллельно)

- **WS-1** (Composition root) — high coupling, но atomic per fix
- **WS-2** (Fail-open) — independent per fix
- **WS-5** (Settings/Config/CVE) — independent per fix (WS-5.1 → WS-5.3 sequential)
- **WS-6** (Library replacement) — independent per fix
- **WS-7** (Agent DSL / RAG) — independent per fix
- **WS-8** (API + Transport parity) — WS-8.8 зависит от WS-2.8
- **WS-9** (Extensions cleanup) — fully independent
- **WS-10** (Pre-existing) — fully independent (developer commit step)

**Рекомендуемая последовательность Sprint 37 fix-wave:**

1. **WS-2** (10 fixes, ~6-8h, разные модули) — fail-open / data integrity
2. **WS-1** (6 fixes, ~10h, composition root) — после WS-2 (composition root
   часто требует fail-closed в facade)
3. **WS-5.1 + WS-5.2 + WS-5.3** (CVE cleanup, ~3h) — security gate
4. **WS-6.1** (test-infra conftest, ~1h, HIGH impact ~40 failing tests) —
   visibility для WS-3
5. **WS-3** (test-masking, ~6-8h, ~8 fixes) — после WS-6.1
6. **WS-7.1 + WS-7.2** (agent security, ~3h) — fail-open + gateway split
7. **WS-4** (workflow DSL registration, ~3h) — после WS-1.5 (Temporal lifecycle)
8. **WS-8** (transport parity, ~5h) — independent
9. **WS-9** (extensions cleanup, ~3h) — independent
10. **WS-6.2..6.12 + WS-7.3..7.10** (cleanup, ~6h) — independent

**Sprint 38+**: WS-1.5 (Temporal lifecycle, ~5d, HIGH risk) — отдельный sprint
после решения по ADR-045.

---

## 7. Library replacement table

> Из отчётов 01 (infrastructure), 03 (services), 06 (dsl), 08 (agents),
> 09 (rag), 10 (extensions), 11 (dependencies). **LOC reduction** — оценка
> аналитика (не верифицировано source-side per инструкции).

| Library | Cited custom code | Installed status (per report) | License / maintenance | Expected LOC reduction | Recommendation |
|---|---|---|---|---|---|
| `cachetools` | `dict + time.monotonic()` в `cache/rag/embedding_cache.py` (cycle 1/T-3.1) | ✓ installed v7.1.7 (infra) | BSD-3-Clause, active (Astral/similar) | −20/+30 net (cycle-1 verified) | **APPLIED ✓** (cycle 1/T-3.1 RESOLVED в working tree, 10/10 tests PASSED) |
| `cachetools.TTLCache` | Custom TTL/RW-lock в `_InMemoryJwtBlacklist` (security:DOMAIN-P3-002) | ✓ installed | BSD-3-Clause, active | ≈ 0 (already optimal) | **NO-OP** (negative finding) |
| `tenacity` | In-line exponential backoff в `outbox/dispatcher.py:273-313` (cycle 2/T-W3-01) | ✓ installed 9.1.4 | Apache-2.0, active (Julien Danjou + maintainers) | ~−40 LOC if applied to outbox dispatcher | **PARTIAL** — applied в 7+ sites, но outbox dispatcher сохранён by-design (per-attempt state preservation, transactional safety). Cycle 2 P0 RESOLVED для большинства use-cases, RESIDUAL для outbox |
| `cachetools.TTLCache` | TTL-cache в `embedding_cache.py` (RAG) | ✓ installed | BSD-3-Clause, active | ≈ 0 (already optimal, Sprint 86) | **APPLIED ✓** (cited as positive example в RAG-P3-001) |
| `jsonschema.Draft202012Validator` | Custom `_apply_json_schema` в `services/ops/data_quality/apply_mixin.py:315-346` (services:DOMAIN-P3-001) | ✓ installed 4.26.0 (services) | MIT, active (python-jsonschema org) | ~−25 LOC | **RECOMMENDED** — `_apply_json_schema` → `Draft202012Validator.validate` (already used в `schema_registry/registry.py:266`) |
| `apprise` | Custom multi-channel notifications в `services/notifications/apprise_service.py` (services:DOMAIN-P3-002) | ✓ installed | MIT, active (100+ backends) | n/a | **NO-OP** (negative finding, no replacement) |
| `langgraph` / `langchain` | Custom `StructuredTool` adapter в `services/ai/ai_graph.py:35-76` (agents:DOMAIN-P3-001) | ✓ installed (pyproject) | MIT, active | n/a | **NO-OP** (negative finding, project-specific ActionHandlerRegistry contract) |
| `RecursiveChunker` (internal) | Custom `chunk_text` в `services/ai/rag_service/ingest_mixin.py:35-48` (rag:RAG-P3-001) | ✓ available (`services/ai/chunkers/`) | Internal (Sprint 36+) | ~+50 LOC net (use existing chunker) | **RECOMMENDED** — replace custom byte-chunking with `get_chunker(strategy, ...)` |
| `python-inn` / `validators` | Custom `validate_inn` в `dsl/helpers/banking.py:31-43` (business-logic:BL-P3-001) | **NOT VERIFIED** в pyproject | (unknown — needs verification) | ≈ 0 (12 LOC custom vs 3rd-party dep + edge cases) | **NOT RECOMMENDED** — current impl OK after BL-P2-003 None guard fix |
| `httpx-retries` / `tenacity` | Hand-rolled `BaseExternalAPIClient` в `extensions/credit_pipeline/services/clients/skb.py:27-133` (business-logic:BL-P3-002) | tenacity ✓ installed (9.1.4), httpx-retries — **NOT VERIFIED** | tenacity Apache-2.0 (verified) | ≈ 0 (BaseExternalAPIClient already abstraction per R-V15-13) | **NOT RECOMMENDED** — risk несовместимости с другими extensions |
| `pydantic-settings` | Custom settings loader (settings:DOMAIN-P3-001) | ✓ installed v2.13 | MIT, active | n/a | **NO-OP** (industrial standard) |
| `watchfiles` | Custom polling для hot-reload (settings:DOMAIN-P3-002) | ✓ installed | MIT, active (Astral) | n/a | **NO-OP** (native FS events + debounce, stdlib equivalent is polling-based) |
| `defusedxml` | Custom fallback `ET.fromstring` в DSL marshal/format_convert (DSL-P0-002/P0-003) | ✓ installed 0.7.1 (DSL) | BSD-3-Clause, active | ≈ 0 (replace or delete fallback) | **RECOMMENDED** — drop-in или удалить fallback (defusedxml — required dep) |
| `xmltodict` | Custom `_xml_to_dict_stdlib` (DSL-P0-003) | ✓ installed 0.15.1 | MIT, active | ≈ 0 (xmltodict — required, fallback dead) | **RECOMMENDED** — delete fallback function |
| `temporalio` | Custom `DurableWorkflowRunner` в `infrastructure/workflow/runner.py:153-461` (workflow:DOMAIN-WF-P3-001) | ✓ installed (mentioned в pyproject, but compiler tests skip when not installed) | MIT, active | ~−461 LOC (thin wrapper вокруг LiteTemporalBackend) | **RECOMMENDED WITH CAUTION** — cycle 2 P0-005 deferred; ADR-045 verification needed |
| `packaging.specifiers` + `packaging.version` | Custom `compensate_map` validator в `dsl/workflow/spec/activity_declarations.py:86-109` (workflow:DOMAIN-WF-P3-002) | ✓ installed (WorkflowLauncher already uses) | Apache-2.0 / BSD-3 | ~−20 LOC | **RECOMMENDED** — simplify validator |
| `temporalio.exceptions` | Custom `_exception_to_result` в `infrastructure/workflow/temporal_backend.py:317-368` (workflow:DOMAIN-WF-P3-003) | ✓ installed | MIT, active | ~−50 LOC | **RECOMMENDED** — Temporal SDK ≥1.20 typed mapping |
| `lxml` / `xml.etree.ElementTree` | Cycle 2 P0-002 RESOLVED (lxml CVE fixed в 6.1.1) | ✓ installed 6.1.1 | BSD-3-Clause, active | n/a | **NO-OP** (CVE fixed) |

**Summary:**

- **3 APPLIED**: cachetools (cycle 1), tenacity (cycle 2 partial), EmbeddingVectorCache via cachetools (RAG Sprint 86)
- **4 RECOMMENDED**: jsonschema (services), RecursiveChunker (RAG), defusedxml (DSL), temporalio (workflow — needs ADR)
- **7 NO-OP / negative**: apprise, langgraph, pydantic-settings, watchfiles, python-inn, httpx-retries, tenacy for BaseExternalAPIClient
- **2 needs verification**: python-inn, httpx-retries (NOT VERIFIED в pyproject)
- **1 partial**: tenacity (custom loop in outbox dispatcher by-design)

---

## 8. Organic feature table

| ID | Benefit | Architecture fit | Evidence | Defer/plan recommendation |
|---|---|---|---|---|
| **security:DOMAIN-P4-001** DSL `agent_security_policy` | Per-workflow policy override в declarative form | DSL processor pattern (`BaseProcessor`) | `dsl/builders/security.py:37-40` currently Python API only | **DEFER** (YAGNI, DSL `agent_security_check` already exists; only if explicit demand) |
| **services:DOMAIN-P4-001** (negative) — нет new feature for adding | n/a | Camel/Airflow style — already 8 check types | services (03) — explicit "no candidate" | **NEGATIVE** |
| **services:DOMAIN-P4-002** (negative) — Jupyter 4 backends already | n/a | Camel-style factory | services (03) | **NEGATIVE** |
| **api:API-P4-001** invocations OpenAPI Idempotency-Key | Surface в OpenAPI для consumer clarity | FastAPI `parameters` schema | `entrypoints/api/v1/endpoints/invocations.py` — relies на middleware | **PLAN (Sprint 38+)** — low effort, organic improvement |
| **api:API-P4-002** OpenAPI / AsyncAPI integration | Per-endpoint summaries → processor catalog | FastAPI OpenAPI hooks | `/api/v1/dsl/processors/catalog` + `/asyncapi` exist | **DEFER** — backlog |
| **dsl:DSL-P4-001** recipient_list `timeout` per-step | Latency protection для sequential recipient routing | `asyncio.wait_for` + config | `dsl/engine/processors/eip/routing/recipient_list.py:50-86` | **PLAN (Sprint 37+)** — low effort |
| **workflow:DOMAIN-WF-P4-001** cron/schedule DSL step | Declarative time-triggered workflows (vs sensor poll) | Camel-style | `dsl/workflow/builder/__init__.py` — no cron/schedule/at() | **PLAN (Sprint 38+)** — moderate effort, real use case |
| **workflow:DOMAIN-WF-P4-002** parallel/fan-out DSL step | Concurrent workflow branches (vs Saga sequential) | Camel `multicast`/`aggregate` | `dsl/workflow/builder/__init__.py` — 17 methods, no parallel() | **PLAN (Sprint 38+)** — moderate effort |
| **workflow:DOMAIN-WF-P4-003** `with_timeout` builder method | Per-step timeout (vs activity-level only) | Step-level decorator | `dsl/workflow/builder/__init__.py` — has `default_timeout`, no `with_timeout` | **PLAN (Sprint 38+)** — moderate effort |
| **agents:DOMAIN-P4-001** LangGraph session resume + durable checkpoint | Contract tests для supported behavior | Live integration test | LangGraph installed in pyproject | **DEFER (post-Sprint 37 wiring fix)** — only after runtime deterministic |
| **rag:RAG-P4-001** Create `tests/e2e/test_text_rag_e2e.py` | Coverage для text-only RAG (multimodal broken per RAG-P0-004) | Ponytail ~120 LOC | cycle 1/T-4.1 deferred, cycle 2/T-W4-01 deferred | **PLAN (Sprint 37+)** — moderate effort, structural debt |
| **rag:RAG-P4-002** Document `multimodal_rag_enabled` vs `multimodal_rag_full` | Feature-flag semantic clarity | Doc-only or merge flags | `_legacy.py:119-127` + `core/config/features/ai_rag.py:101` | **PLAN (Sprint 37+)** — XS effort |
| **business-logic:BL-P4-001** scoring_agent real ML model | Replace rule-based placeholder | Sprint 8+ backlog (per docstring) | `extensions/credit_pipeline/agents/__init__.py:54-138` | **DEFER (Sprint 8+)** — long-term roadmap |
| **settings:DOMAIN-P4-001** Compose resource limits | Same as P0-001, downgraded для dev/staging parity | k8s+helm has limits | `ops/compose/*.yml` | **PLAN (Sprint 37+)** — low effort; downgrade до P3 если compose только dev |

**Summary:**

- **3 NEGATIVE** (services:DOMAIN-P4-001/002, agents:DOMAIN-P4-001 defer) — уже покрыто или deferred
- **5 PLAN (Sprint 37+)** — low-to-moderate effort, real use cases:
  - api:API-P4-001 (invocations OpenAPI)
  - dsl:DSL-P4-001 (recipient_list timeout)
  - rag:RAG-P4-001 (text-RAG E2E) — **CRITICAL: structural debt**
  - rag:RAG-P4-002 (multimodal_rag flag doc)
  - settings:DOMAIN-P4-001 (compose limits)
- **5 PLAN (Sprint 38+)** — moderate effort:
  - workflow:DOMAIN-WF-P4-001 (cron/schedule DSL)
  - workflow:DOMAIN-WF-P4-002 (parallel/fan-out)
  - workflow:DOMAIN-WF-P4-003 (with_timeout)
- **2 DEFER**:
  - security:DOMAIN-P4-001 (YAGNI)
  - business-logic:BL-P4-001 (real ML — Sprint 8+)
- **1 DEFER (post-Sprint 37)**:
  - agents:DOMAIN-P4-001 (LangGraph contract tests)

---

## 9. Итог: какие P0/P1 блокируют порог ≥80 для каждого домена

> Scores в этой секции — **self-assessment** аналитика (разные формулы),
> только как witness of readiness. Не суммировать и не усреднять.

| Domain | Cap-rule satisfied? | Blocking P0 | Blocking P1 | Sprint 37 minimum |
|---|:-:|---|---|---|
| **01 infrastructure** | ✗ | — | 01-P1-NEW-001 (sink/DLQ test-infra conftest — ~40 failing tests) | Add autouse fixture grants `dlq.write`/`file.write`/etc. |
| **02 security** | ✗ | DOMAIN-P0-001 (validate_sql drop), P0-002 (AuthValidateProcessor permanent fail-closed), P0-003 (capability audit data-loss) | DOMAIN-P1-002 (5 entrypoints deprecated shim imports) | Fix all 4 — fix is small (kwargs propagation + decorator signature + async `_emit_audit` + 5 import replacements) |
| **03 services** | ✗ | DOMAIN-P0-001 (TenantFacade TypeError), P0-002 (admin audit_callback unwired), P0-003 (audit DLQ unwired), P0-004 (PII fail-open), P0-005 (admin AuthZ fail-open) | DOMAIN-P1-001 (data_quality dataclasses 5-way dup), P1-002 (check vs remediate), P1-003 (3 shim callers), P1-004 (cron dashboard ambiguous) | Composition root wiring (P0-002, P0-003) + fail-open → fail-closed (P0-001, P0-004, P0-005) + data_quality consolidation (P1-001, P1-002) |
| **04 entrypoints** | ✗ | DOMAIN-P0-001 (SSE principal/permissions), P0-002 (MQ subscribers ACK vs DLQ) | DOMAIN-P1-001..004 (transport parity WS/Webhook/Express/gRPC) | Fix SSE principal + MQ DLQ handoff + 4 transport parity fixes |
| **05 api** | ✗ | API-P0-001 (HITL authz), API-P0-002 (admin_cron RCE), API-P0-003 (generator/setup.py broken import) | API-P1-001 (admin_nats importlib), P1-002 (generator/setup.py dead code), P1-003 (admin_cron whitelist) | HITL Depends + admin_cron whitelist + delete generator/setup.py |
| **06 dsl** | ✗ | DSL-P0-001 (ScanFile fail-open), P0-002 (marshal XXE fallback), P0-003 (format_convert XML fallback active vuln) | DSL-P1-001..003 (idempotency/dedup fail-open + waf_check semantic) | XML helpers consolidation (defusedxml) + `fail_closed=True` params + waf_check dotted-path fix |
| **07 workflow** | ✗ | DOMAIN-WF-P0-001 (WorkflowFlags docstring lie), P0-002 (4 processors без `@processor`), P0-003 (ActivityBridge.decorate не вызывается), P0-004 (TemporalWorkerPool не инстанцируется), P0-005 (cancel vs invoke sync semantics) | DOMAIN-WF-P1-001 (silent exceptions), P1-002 (WorkflowHandle kwargs), P1-003 (Protocol vs Temporal) | composition fix (P0-002, P0-003, P0-004 — Sprint 38+ для P0-004) + flags defaults (P0-001) + sync semantics (P0-005) |
| **08 agents** | ✗ | DOMAIN-P0-001 (AI service factory NotImplementedError), P0-002 (AGENT_TOOL_POLICY_FAIL_OPEN), P0-003 (gateway vs chat model split) | DOMAIN-P1-001 (build_and_run_agent kwargs mismatch), P1-002 (sandbox audit `pass`) | Composition root fix + remove fail-open env override + gateway unification + kwargs fix + sandbox audit fix |
| **09 rag** | ✗ | RAG-P0-001 (SystemExit bypass), P0-002 (RagCachePrewarmer broken), P0-003 (get_rag_service fallback dead), P0-004 (multimodal E2E failing) | RAG-P1-001 (rag_query_stats byte/str), P1-002 (_run BaseException cascade) | PII `except (Exception, SystemExit)` + Prewarmer replace `query()` → `augment_prompt()` + factory pattern + multimodal E2E fix |
| **10 business-logic** | ✗ | BL-P0-001 (dead saga imports) | BL-P1-001 (OSINT fail-OPEN banking), P1-002 (credit_pipeline_v2 default drift) | Remove dead saga imports + OSINT data_source marker + flag default consistency |
| **11 dependencies** | ✗ | DEPS-P0-001 (8 stale CVE), P0-002 (streamlit без upper), P0-003 (4-way CVE drift) | DEPS-P1-001 (deptry/creosote не в CI), P1-002 (stale comments) | Cleanup 8 stale CVE + streamlit pin + unify 4 CVE enforcement sites |
| **12 settings** | ✓ (no NEW P0/P1) | (all RESIDUAL cycle-2) | DOMAIN-P1-001 (Granian config surface dup), P1-002 (config_audit.py wrong path) | Compose limits (P0) + hardcoded timeout (P0) + Granian consolidation + config_audit fix |

**Verdict:**

- **11 доменов** имеют **active P0/P1 blockers** против порога ≥80.
- **Домен 12 (settings)** имеет 0 NEW P0/P1, но требует cleanup RESIDUAL cycle-2
  (P0 compose + P0 hardcoded timeout — dev experience, не production blocker).
- **5+ test-masking issues** из cycle 2 PHASE-2 §5.3 **подтверждены в cycle 3**
  (консенсус; см. §1.4).
- **Приоритет Sprint 37 fix-wave** (см. §6): WS-2 (fail-open) → WS-1
  (composition root) → WS-5 (CVE cleanup) → WS-6.1 (test-infra) → WS-3
  (test-masking) → WS-7 (agent/RAG critical) → WS-4 (workflow DSL) →
  WS-8 (transport parity) → WS-9 (extensions cleanup) → WS-6 (minor).
- **WS-1.5 (Temporal Worker lifecycle)** — Sprint 38+ (требует ADR-045
  verification, HIGH risk, ~5d).
- **WS-10 (pre-existing test failures)** — developer commit step, не cycle-3
  swarm attribution.

---

## Приложение: agents vs cycles attribution matrix

| Cycle | T-1.1 | T-1.2 | T-1.3 | T-1.4 | T-1.5 | T-2.1 | T-3.1 | T-4.1 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Reported (verified) | extension ok | SSE auth RESIDUAL | MQ DLQ RESIDUAL | EIP RESOLVED ✓ | policy_mixin RESOLVED ✓ | extensions clean | cachetools RESOLVED ✓ | text-RAG RESIDUAL |

| Cycle-2 | T-W1-01 | T-W1-02 | T-W1-03 | T-W1-04 | T-W1-05 | T-W1-06 | T-W1-07 | T-W1-08 | T-W2-* | T-W3-01 | T-W4-01 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Reported (verified) | PARTIAL (test ok, runtime fail) | n/a | RESIDUAL (= DOMAIN-P0-002) | RELATED (= DOMAIN-P0-003) | RESOLVED ✓ | n/a (RAG) | RESIDUAL (= DOMAIN-P0-001 SSE) | RESOLVED ✓ (extensions) | layer track CONFIRMED | tenacity RESOLVED ✓ | text-RAG RESIDUAL |

| Cycle-3 | P0 | P1 | P2 | P3 | P4 | Status |
|---|--:|--:|--:|--:|--:|---|
| 01 infrastructure | 0 | 1 | 1 | 1 | 0 | cap 79 (P1) |
| 02 security | **3** | 2 | 1 | 2 | 1 | 0 (clamped) |
| 03 services | **5** | 4 | 3 | 2 | 2 | 0 (clamped) |
| 04 entrypoints | **2** | 5 | 7 | 1 | 0 | 0 (clamped) |
| 05 api | **3** | 3 | 3 | 3 | 2 | 19 |
| 06 dsl | **3** | 3 | 2 | 2 | 1 | 25.5 |
| 07 workflow | **5** | 3 | 6 | 3 | 3 | 0 (floor) |
| 08 agents | **3** | 2 | 2 | 1 | 1 | 20 |
| 09 rag | **4** | 2 | 2 | 2 | 2 | 24 |
| 10 business-logic | 1 | 2 | 7 | 2 | 1 | 79 |
| 11 dependencies | **3** | 2 | 2 | 2 | 0 | 35 |
| 12 settings | 0 NEW (4 RESIDUAL) | 2 | 4 | 2 | 1 | 65 |

---

## Подпись

- **Никакие файлы source/configs/lockfiles/allowlists не модифицировались.**
- **Единственный артефакт записи — этот файл.**
- **Cycle-1/cycle-2 markdown, `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md` НЕ
  читались.**
- **Численные assertions — только из runtime-проверок phase-1 аналитиков.**
- **Scores per domain — self-assessment с разными формулами; не агрегировать.**