# DECISIONS.md

## Устойчивые решения проекта

### Базовые правила работы (наследуются)

- Graphify — основной источник знания о связях модулей.
- Любые изменения выполняются только после точного плана.
- Для новых фич сначала AskUserQuestion, затем план, затем реализация.
- Commit только по явной команде пользователя.
- Push и release без отдельного подтверждения запрещены.
- Тесты не навязывать и не предлагать по умолчанию.
- Верификация — через Makefile-команды проекта.
- `.claude/` — служебная память Claude, не пользовательская документация.

---

## ADR из GAP-аудита 2026-05-21 (Sprint 17 architectural backbone)

Источник: сквозной 10-слойный GAP-аудит pre-production (L1–L10). Все четыре ADR принимаются единым backbone для Sprint 17 «Centralization Hardening». Полные findings — `.claude/KNOWN_ISSUES.md` секция GAP-аудит 2026-05-21.

### ADR-NEW-1: AuthorizationGateway — единая точка авторизации

**Контекст**. L8 Security аудит выявил разрозненную проверку capability в разных местах: CapabilityGate в plugin_runtime, CapabilityPolicy в core/security, Casbin в infrastructure/policy/casbin_adapter.py, OPA-client отдельно. DSL не консультирует OPA на runtime. Audit-логирование решений распределено и не унифицировано.

**Решение**. Создать `core/security/authorization_gateway.py::AuthorizationGateway` с методом `authorize(principal, resource, action, context) -> AuthorizationDecision`. Внутри — последовательная композиция:
1. `CapabilityGate.check(plugin, capability, scope)` (V11.1 enforcement)
2. `CapabilityPolicy.evaluate(...)` (если задано)
3. `Casbin.enforce(...)` (если enabled для tenant)
4. `OPA.query(...)` (если enabled для resource)

Единый `correlation_id` propagation; единый audit-event `authorization.decision` на каждое решение (allow/deny + reason chain).

**Обоснование**. Defence-in-depth без дублирования логики; единая точка для аудита; разработчик знает «где смотреть, кто запретил»; pluggable policy-engines (OPA opt-in без edit ядра).

**Последствия**. (+) Полное покрытие auth-решений audit-логом. (+) Чистый расширяемый контракт. (−) Миграция всех endpoint-guard'ов на gateway (~30 callsites). (−) Дополнительный latency 1–3ms на проверку (mitigated LRU-кэшем как в CapabilityGate).

**Wave**: `[wave:s17/k1-w2-authorization-gateway]`.

---

### ADR-NEW-2: Decoratively Composable Middleware Chain

**Контекст**. L1 Gateway/Middleware аудит выявил, что middleware-цепочка в `entrypoints/middlewares/setup_middlewares.py` жёстко закодирована (26 middleware в python-коде). Plugin'ы не могут добавлять собственные middleware без edit ядра. Per-route override невозможен. Нет entry_points-группы или pluggy-hook.

**Решение**. Ввести declarative middleware composition:
1. `plugin.toml::[[middleware]]` секция (`name`, `module`, `order`, `enabled_routes`, `disabled_routes`).
2. Entry-points-группа `gd_integration_tools.middleware_hooks` для external-пакетов.
3. `MiddlewareRegistry` в `entrypoints/middlewares/registry.py` — собирает middleware из плагинов на startup + сортирует по `order`.
4. Per-route override через `route.toml::[middleware]` (включить/выключить отдельные mw для маршрута).
5. Сохранение backward-compat: текущий `setup_middlewares.py` остаётся entry point, но делегирует регистрацию в MiddlewareRegistry.

**Обоснование**. R-V15-1 plugin autonomy не работает без этого; R-V15-decl declarative-first; не нарушает Single Entry — registry-singleton.

**Последствия**. (+) Plugin'ы расширяют функциональность без core-edit. (+) Per-route override решает текущий gap (TimeoutMiddleware один global). (−) Сложность дебага при ошибках композиции; mitigated через `make middleware-tree` (визуализация цепочки) + integration test на pre-prod-check.

**Wave**: `[wave:s17/k3-w2-middleware-registry]` (NEW).

---

### ADR-NEW-3: Unified RequestContext

**Контекст**. L1 аудит выявил разрозненное хранение request-контекста: `request.state.auth` (AuthContext), `request.state.correlation_id` + contextvar, `request.state.tenant_id` + contextvar (дублирование), `client_id` только в audit-event. Разработчик путается, DI-провайдеры резолвят из разных мест, OTel `trace_id`/`span_id` не пробрасываются в structlog logs (L7 critical gap).

**Решение**. Создать `core/request_context.py::RequestContext` dataclass (frozen):
```python
@dataclass(frozen=True, slots=True)
class RequestContext:
    correlation_id: str
    request_id: str
    trace_id: str | None  # OTel
    span_id: str | None
    tenant_id: str | None
    auth: AuthContext | None
    client_id: str | None
    method: str
    path: str
```
Один раз собирать в `RequestContextMiddleware` (первая middleware после exception-handler), затем bind в `contextvars` + `request.state.ctx`. Все downstream-компоненты (DSL processors, services, audit) получают через `RequestContext.current()` или DI-провайдер. structlog `bind_contextvars` (correlation_id, trace_id, tenant_id) — автоматически.

**Обоснование**. Один источник правды; logs/traces корреляция через trace_id; eliminates duplication; упрощает testability (создание fixture).

**Последствия**. (+) Logs/traces/metrics correlate через trace_id. (+) DI-провайдеры упрощаются. (−) Миграция 30+ callsites (mitigated скриптом `tools/migrate_request_context.py`). (−) Backward-compat: `request.state.correlation_id` остаётся как deprecated alias.

**Wave**: `[wave:s17/k3-w1-correlation-id-end-to-end]` (расширен).

---

### ADR-NEW-4: CapabilityGateway Protocol в core/interfaces

**Контекст**. L2 Core Kernel аудит: `core/interfaces/` содержит 8 Protocol-ов, но НЕТ Protocol для CapabilityGate. Текущий `CapabilityGate` — конкретный класс в `core/plugin_runtime/`, импортируется напрямую. Это нарушает Clean Architecture (core зависит от plugin_runtime), затрудняет mock в тестах, не позволяет swap-impl.

**Решение**. Вынести Protocol в `core/interfaces/capability_gateway.py`:
```python
@runtime_checkable
class CapabilityGatewayProtocol(Protocol):
    def check(self, plugin: str, capability: str, scope: str | None = None) -> None: ...
    def declare(self, plugin: str, capabilities: Iterable[str]) -> None: ...
    def list_allocated(self, plugin: str) -> tuple[str, ...]: ...
```
Текущий `core/plugin_runtime/capability_gate.CapabilityGate` имплементирует Protocol; DI binding в `svcs_registry`. AuthorizationGateway (ADR-NEW-1) использует Protocol, не конкретный класс.

**Обоснование**. Clean Architecture; testability (FakeCapabilityGateway для unit-тестов плагинов); пара с ADR-NEW-1 (gateway-of-gateways). Симметрично существующим Protocol-ам (LLMProvider, MemoryBackend, BrowserAutomation).

**Последствия**. (+) Mock-friendly. (+) Возможна замена implementation (например, OPA-only вариант). (−) Один дополнительный indirection слой; mitigated тем, что фактический класс остаётся тот же.

**Wave**: `[wave:s17/k1-w2-authorization-gateway]` (включено в ту же wave).

---

---

## ADR из Phase B критического ultrathink-обзора 2026-05-21 (Sprint 17 review + S18/S19 incorporation)

Источник: Phase B критический разбор плана + Stakeholder M-B (Multi-BU одного банка) решение пользователя 2026-05-21. ADR-NEW-5..11 отражают 7 фундаментальных вопросов (B-1..B-7), вышедших за рамки уже принятых ADR-NEW-1..4. Все семь приняты к проработке, реализация — в S18/S19 wave.

### ADR-NEW-5: AI Safety Capability Vocabulary Unification (B-3)

**Контекст**. V15 правило R-V15-4 декларирует одновременно:
- `fs.write.*` **запрещена** для AI-плагинов;
- `fs.create_new.<workspace>` **разрешена** (только новые файлы в `${AI_WORKSPACE}/<tenant>/<session>/<artifact>`).

Это **same operation (write) с разным scoping** — historical artifact ранних итераций capability модели. Сейчас 2-capability подход для одного действия создаёт когнитивную нагрузку: разработчик плагина видит две capability и не знает какую заявить; runtime поддерживает два code-paths; audit-log имеет неоднородные events.

**Решение**. Ввести единую capability `fs.write.<scope>` с обязательным `scope`:
- AI-плагины декларируют `fs.write.workspace.<id>` (scope = `workspace.<workspace_id>`);
- Production-плагины декларируют `fs.write.tenant.<tenant_id>` или `fs.write.repo.<area>` (только для системных, не AI);
- Запрет (`CapabilityDeniedError`) для AI-плагинов на `fs.write.repo.*` остаётся.

Legacy `fs.create_new.<workspace>` → **deprecated alias**: при декларации в `plugin.toml` `CapabilityRegistry.resolve()` переводит в `fs.write.workspace.<id>` + emit `audit.capability.deprecated_alias` warning (1 раз на plugin load). Удаление alias — post-S20 (V23 backlog).

**Обоснование**. Один путь = один code-path = одна точка аудита. Симметрично с `fs.read.<path>` (один scope-based pattern). Устраняет конфузию «`fs.create_new` ≠ `fs.write` хотя fizz-buzz та же операция».

**Последствия**. (+) Единый scope-based vocabulary. (+) Audit-event homogeneity. (−) Migration 3 существующих AI-плагинов на новую capability (rename в `plugin.toml`); mitigated deprecated alias на N релизов. (−) Документация update обязательна (workspace_manager docstring + onboarding-guide).

**Wave**: `[wave:s19/k1-w5-ai-safety-capability-unify]` (S19 К1, 2-3 дня).

---

### ADR-NEW-6: Plugin Trust 2-tier Model (B-4)

**Контекст**. F-2 sandbox overhead 137% (`tests/perf/test_plugin_sandbox_overhead.py`, S14 carryover в S18) — это фундаментальный лимит `psutil`-polling implementation `_with_resource_limits`. Не оптимизационная задача: 2 psutil snapshots на каждый `PluginSandboxAdapter.run` дают непреодолимый floor ~120-200%. Все текущие 3 плагина (`example_plugin`, `credit_pipeline`, `core_entities`) — **trusted internal code**, написаны самим банком, проходят code-review.

**Решение**. Ввести `plugin.toml::trust_tier = "A" | "B"`:
- **Tier-A** (trusted, signed by org-CA cosign): runtime sandbox **отключён**; isolation обеспечивается через:
  - capability-gate (V11.1) — обязателен;
  - mandatory code-review CI gate (`.github/CODEOWNERS` + ADR-driven approval);
  - supply-chain (cosign signature verify на startup + SBOM check);
  - `plugin.toml::call_function_modules` whitelist (K-ARCH-5 enforce).
- **Tier-B** (untrusted/external/customer-provided): **strict e2b/pyodide** sandbox; capability `code.execute.<runtime>` обязательна.

Существующие 3 плагина → **Tier-A по умолчанию** (signed by org-CA в supply-chain pipeline). Закрытие F-2 — через model change, не sandbox-tuning. Numeric DoD S18 для F-2 (overhead <5%) **снимается для Tier-A** (overhead = 0, no sandbox); сохраняется для Tier-B (e2b natively < 5% per its design).

**Обоснование**. Симметрично с industry pattern (Apache Pulsar trust tiers / GitHub Actions trusted vs fork PR). Trust анализ соответствует stakeholder M-B (Multi-BU одного банка — все плагины internal). Avoid overengineering: F-2 решается архитектурно, не tuning.

**Последствия**. (+) F-2 closure без psutil-optimization (тупиковая ветка). (+) Production-ready trust model для будущих 3rd-party plugins. (−) Cosign-signing pipeline должен быть extended (multi-artifact: `*.whl` + `plugin.toml`); частично реализован в supply-chain (S18 К1 W2 `make security`). (−) ADR R1.20 (S18) переопределяется: «sandbox overhead» теряет статус single DoD critium → DoD S18 #11 переформулируется.

**Wave**: `[wave:s18/k1-w5-plugin-trust-2tier]` (S18 К1, **замещает** `[wave:s18/k2-w3-sandbox-f2-final]`). DoD S18 расширяется до 18 критериев.

---

### ADR-NEW-7: Production Hot-Reload Disable + Plugin Inventory Hash (B-5)

**Контекст**. V22 DoD «Hot Reload < 3 сек» (DSLYamlWatcher + PluginLoader.hot_swap + RouteLoader.hot_reload) полезен для dev/staging, но конфликтует с **banking compliance**:
- При production-инциденте audit-team спрашивает «какая версия plugin/route была в момент HH:MM:SS?»;
- Hot-reload меняет код in-process без unique restart-marker → reconstruction невозможна;
- Atomic upgrade (drain + restart) — стандарт banking deployments.

**Решение**. При `APP_PROFILE=prod` все hot-reload пути **отключены**:
- `DSLYamlWatcher.start()` — no-op (или вообще не регистрируется в lifespan под `if app_profile != 'prod'`);
- `PluginLoader.hot_swap()` — raises `OperationNotPermittedInProductionError`;
- `RouteLoader.hot_reload()` — то же.

Plugin/Route inventory **SHA-256 hash** embed в каждый audit-event:
- На startup compute `PluginInventorySnapshot.hash()` = SHA-256(sorted(plugin_name@version × route_name@version × middleware_name@version));
- Bind в structlog `bind_contextvars(plugin_inventory_hash=...)` для всех audit-event;
- Persist в ClickHouse audit-table column `plugin_inventory_hash`.

Apt-style graceful upgrade (drain → new container deploy → atomic switch) реализуется отдельным workflow (`ops/deploy/atomic-rollout.sh`), не in-process.

**Обоснование**. Banking compliance: SOX / PCI DSS требуют immutable audit-trail of what code was running. Hot-reload — известный анти-паттерн в финансовых системах. Dev/staging остаются с hot-reload (DX requirement). Inventory hash — cheap (compute on startup, immutable per run), но даёт forensic reconstruction.

**Последствия**. (+) Production immutability + audit-trail. (+) Dev DX сохраняется (hot-reload в dev_light / staging). (−) Production deploy цикл — атомарные restart (acceptable, есть K8s rolling update). (−) Hot Reload < 3 сек DoD V22 переформулируется на dev_light only.

**Wave**: `[wave:s19/k1-w6-prod-hot-reload-disable]` (S19 К1, 1-2 дня).

---

### ADR-NEW-8: Streamlit Split — Dev Portal vs Production Admin (B-7)

**Контекст**. 80+ Streamlit pages в `frontend/streamlit_app/pages/` смешивают:
- **Developer portal** (DSL Visual Editor, RAG sandbox, workflow templates, code-clone gate UI);
- **Production admin** (audit log viewer, feature-flags toggle, plugin inventory, user/tenant management, capability grants, audit replay).

Streamlit не имеет встроенного:
- RBAC (нет per-page permission check, нет integration с Casbin/OPA);
- Audit-trail UI-clicks (каждый click admin action должен быть в `audit.admin_action`);
- Proper SSO для banking (только OAuth-base-proxy, не SAML+AD из S18).

**Решение**. Двухпортальная архитектура:
- `frontend/streamlit_app/` — **developer portal** (только dev_light / staging access; production VPN-restricted). 80+ pages сохраняются;
- `frontend/admin-react/` (NEW, S19) — **React + Vite + FastAPI admin endpoints** для production admin: 5-7 критических страниц:
  1. **Audit log viewer** (filter by correlation_id/tenant/action; export CSV);
  2. **Feature flags admin** (per-tenant toggle с audit-event);
  3. **Plugin inventory** (read-only: name/version/capabilities/inventory_hash);
  4. **User management** (CRUD на user-table + role/tenant assignment);
  5. **Capability grants** (admin может grant capability на time-limited basis с audit);
  6. **Audit replay** (re-execute action с full audit-chain).
- Полный RBAC через `AuthorizationGateway.authorize(principal=admin_user, resource="admin.audit_log", action="read")` (ADR-NEW-1);
- Audit-trail каждого UI-клика: middleware на React App → `audit.admin_action` с trace.

Streamlit pages не дублируются для admin — переключение по `if request.user.is_admin and APP_PROFILE == 'prod': redirect_to_admin_react()`.

**Обоснование**. Streamlit отлично для DX / experimentation (быстрый Python). React + FastAPI правильнее для production admin (proper RBAC, audit, SSO, accessibility). Не выкидываем 80 страниц — split по назначению.

**Последствия**. (+) Production admin с proper SSO + RBAC + audit. (+) DX через Streamlit сохраняется. (−) Новый stack для команды (React + Vite + TypeScript) — частично mitigated, поскольку команда уже знакома с FastAPI/REST. (−) Initial MVP — только 5-7 страниц (не все 80); остальные миграции в post-V22 backlog при необходимости.

**Wave**: `[wave:s19/k5-w5-admin-react-mvp]` (S19 К5, 5-6 дней). Streamlit pages не дублируются.

---

### ADR-NEW-9: Multi-Tenancy Scope Reduction = M-B Logical (B-6)

**Контекст**. V22 декларирует full multi-tenancy:
- `TenantContext` + per-tenant SLO/quota/encryption;
- Encryption-per-tenant (KMS-derived key per tenant);
- IDS (Intrusion Detection System) per tenant.

**Реальный stakeholder** (пользователь подтвердил 2026-05-21): **M-B Multi-BU одного банка** (Multi Business Unit single bank), не M-C (multi-organization SaaS-провайдер). Различие критическое:
- M-B: logical separation между БУ (corporate / retail / treasury), общая инфраструктура, общий security perimeter, ACL + audit per BU;
- M-C: physical/cryptographic isolation, encryption-per-tenant обязательно, IDS opt-in.

Текущая V22 архитектура — **overkill для M-B**: encryption-per-tenant добавляет 30-50% kms-call overhead без compliance-benefit (банк всё равно владеет всеми BU); IDS-per-tenant дублирует existing perimeter SIEM.

**Решение**. Scope reduction до M-B:
- **`TenantContext` остаётся** (для BU-разграничения; contextvar propagation, audit `tenant_id`, structlog `bind_contextvars`);
- **Per-tenant SLO/quota** — упрощается до **per-BU rate-limit + budget** (на уровне Casbin/OPA policies; `fastapi-limiter` с tenant-aware namespace из S2);
- **Encryption-per-tenant** — **удаляется** из scope V22 (`infrastructure/security/tenant_encryption.py` — wired-but-unused; перенос в `post-v22-backlog/` для будущего M-C use case);
- **IDS-per-tenant** — также удаляется (общий SIEM-pipeline через Graylog);
- **ACL + audit per BU** — реализуется через `AuthorizationGateway` (ADR-NEW-1) + `AuditService.correlation_id` (S17 К3 W3).

**Обоснование**. YAGNI / KISS. M-C — гипотетический use case (не текущий stakeholder); готовиться к нему ценой production complexity не оправдано. M-B полностью реализуем через existing capability-gate + ACL + audit. Если M-C появится в roadmap (V23+), revert этого ADR — это linear-cost migration (TenantContext propagation остаётся, добавляется encryption layer).

**Последствия**. (+) ~30-50% latency reduction в data-path (no per-tenant KMS round-trip). (+) Production complexity снижается. (+) Backbone для banking M-B (стандартный pattern). (−) Удаление кода `tenant_encryption.py` (~200 LOC) — задокументировано в migration note. (−) ADR при появлении M-C use case revert-able.

**Wave**: `[wave:s18/k1-w6-multi-tenancy-mb-reduce]` (S18 К1, 2-3 дня). Удаляет encryption-per-tenant код + IDS-stub, оставляет logical separation (TenantContext + ACL + audit).

---

### ADR-NEW-10: DSL Surface Trimming via Usage-Audit (B-1)

**Контекст**. DSL surface size:
- 150+ методов `RouteBuilder` (`dsl/route/builder/*.py` миксины);
- 19 blueprints (`dsl/blueprints/`);
- 50+ процессоров (`dsl/engine/processors/`).

Usage **не измеряется**: нет grep-counter callsites; LSP не показывает usage в hover; разработчик плагина не знает, какой method — core, а какой experimental. Risk: **мёртвый код** + cognitive overload + maintenance burden.

**Решение**. Введение `make dsl-usage-audit` (новый Make target):
- Скрипт `tools/audit/dsl_usage_audit.py` собирает callsites каждого DSL-method из:
  - `routes/<name>/*.dsl.yaml` (YAML keys);
  - `extensions/<name>/**/*.py` (Python `.method_name()` calls);
  - `tests/` (тестовые применения);
- Methods с **< 5 callsites** помечаются `@deprecated` (Python: `@warnings.deprecated`) + warning в LSP completion ("⚠ deprecated, used in only N routes");
- JSON report `audit-out/dsl_usage_report.json` + Streamlit page `frontend/streamlit_app/pages/86_DSL_Usage_Audit.py`;
- Deprecation period: **2 спринта** (S19 deprecation, S20+1 removal);
- Целевая метрика: **150 → 70-90 cohesive методов к V23**.

**Обоснование**. Lean DSL surface = easier onboarding + faster autocompletion (LSP responsiveness) + меньше points of failure. Deprecation period даёт extensions time для миграции. Removal не в S19/S20 — оставляет safety buffer для V22 production-rollout.

**Последствия**. (+) Cleaner DSL для V23. (+) Measurable maintenance metric (`dsl_methods_count`). (−) Один новый Streamlit page (но это developer portal — соответствует ADR-NEW-8). (−) Возможна резистентность extension owners к deprecation (mitigated через 2-сприint period + ADR-driven review).

**Wave**: `[wave:s19/k3-w6-dsl-usage-audit]` (S19 К3, 2 дня; deprecation в S19, removal — post-V22).

---

### ADR-NEW-11: Multi-Backend Tier-A/B Explicit Scope (B-2)

**Контекст**. PLAN.md / ARCHITECTURE.md заявляют multi-backend support:
- **DB**: PG ↔ Oracle ↔ MSSQL ↔ MySQL ↔ DB2 (5 backends);
- **MQ**: Kafka ↔ RabbitMQ ↔ Redis Streams ↔ NATS (4 backends);
- **Storage**: S3 ↔ MinIO ↔ LocalFS (3 backends).

Test matrix: N²×backends → нереально поддерживать в CI (12 backends × ~20 integration tests × 3 chaos = 720 test combinations). **Реально используется**: 1-2 каждого (PG + Oracle dev, RabbitMQ primary, S3 production / MinIO local).

**Решение**. Двух-tier model:
- **Tier-A (production-supported)**:
  - DB: **PG + Oracle**;
  - MQ: **RabbitMQ + Kafka** (Kafka добавлен для credit-pipeline EventBus);
  - Storage: **S3 + MinIO** (S3 prod, MinIO local-test);
  - **CI**: full integration test + perf-gate + chaos test;
- **Tier-B (community-best-effort)**:
  - DB: MSSQL / MySQL / DB2;
  - MQ: Redis Streams / NATS;
  - Storage: LocalFS;
  - **CI**: minimal smoke test (driver loads + 1 round-trip); без perf/chaos.

`pyproject.toml` extras разделить:
- `db-tier-a = ["asyncpg", "oracledb"]`;
- `db-tier-b = ["aioodbc", "aiomysql", "ibm_db"]`;
- `mq-tier-a = ["aiokafka", "aio-pika"]`;
- `mq-tier-b = ["redis-streams", "nats-py"]`;
- `storage-tier-a = ["aioboto3", "minio"]`;
- `storage-tier-b = ["aiofiles"]` (LocalFS только через aiofiles).

README + `docs/backends.md` явная декларация: «Tier-A — production-supported, Tier-B — community-best-effort (issues приветствуются; PR — обязательны)».

**Обоснование**. Honest scope = sustainable maintenance. Promise-it-all = inability-to-maintain. Tier-B remains usable (driver не удаляется), но без CI gate — пользователь Tier-B принимает risk on himself.

**Последствия**. (+) CI cycles снижаются в N раз (12 → 5 actively-tested backends). (+) Documentation truthfulness (нет «we support DB2» если на самом деле нет). (−) Возможен фрикшн в community при downgrade backend в Tier-B (mitigated через explicit ADR-driven communication). (−) Pyproject extras добавляются (~6 new) — minor churn.

**Wave**: `[wave:s18/k5-w5-multi-backend-tiers]` (S18 К5, 2-3 дня). Без удаления кода; только scope declaration + test pruning + pyproject restructure.

---

### Не принятые в этом раунде (рассмотрение Sprint 18+)

- **Saga State Model + persistence** — отнесено в S18/S19 backlog как операционная задача (не ADR backbone).
- **Public Testkit API** для extensions — отнесено в S19 DX backlog (под VSCode extension).
- **Multi-Region Active-Active** — post-V22 (V23+ для M-C use case если активируется).
- **Per-tenant cryptographic isolation** — post-V22 (см. ADR-NEW-9 revert path).

---

## ADR из DEEP-RESEARCH Sprint 21-23 (post-production gap-backlog)

Источник: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` (Hermes Agent ultrathink, 10 L1–L10 субагентов). После Sprint 20 (`v1.0.0-production`) запускается post-production backlog S21-S23 (PLAN.md V22.2 FINAL §4) для закрытия 28 нерешённых GAP-пунктов. 4 новых ADR (ADR-NEW-12..15) — backbone S21/S23.

### ADR-NEW-12: Row-Level Security (RLS) Strategy для multi-tenant PostgreSQL таблиц

**Контекст**. После M-B scope reduction (ADR-NEW-9) `tenant_encryption.py` удалён, но logical separation между BU остаётся необходимой. Текущая защита: `TenantContextMiddleware` + ACL в коде + audit `tenant_id`. Уязвимости:
- Cache poisoning: один BU подсовывает другому свой `tenant_id` через cache-key prefix injection (B-03 в DEEP-RESEARCH).
- Application-bug: разработчик забывает фильтр `WHERE tenant_id = :tid` в новом query → cross-BU data leak.
- Audit-trail неполная: SELECT без `tenant_id` в WHERE не отлавливается.

**Решение**. PostgreSQL Row-Level Security (RLS) на уровне БД:
1. Alembic-миграция для multi-tenant таблиц (`orders`, `users`, `files`, `audit_log`, `routes_state`):
   ```sql
   ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON orders
     USING (tenant_id = current_setting('app.tenant_id')::uuid);
   ```
2. `TenantContextMiddleware` (S17 ADR-NEW-3 RequestContext) per-request `SET LOCAL app.tenant_id = '...'` в начале транзакции.
3. Feature-flag `RLS_POSTGRES_ENFORCE` (default-OFF в S21 backbone; flip default-ON в S22 после testing).
4. Tests: `tests/security/test_rls_isolation.py` — 5 сценариев leakage (cache poisoning attempt / cross-BU SELECT / WHERE filter bypass / TRIGGER bypass / SUPERUSER override-attempt).

**Обоснование**. Defence-in-depth: даже при application-bug RLS блокирует cross-BU SELECT/UPDATE/DELETE. PostgreSQL feature, не требует custom infrastructure. Стандарт banking compliance (SOX section 404 audit-trail).

**Последствия**. (+) Database-enforced isolation в дополнение к application-layer. (+) Audit-trail полная (PG logs RLS violations). (+) M-B → M-C migration path remains (см. ADR-NEW-9 revert path). (−) Alembic migration требует downtime на ALTER TABLE (mitigated CONCURRENTLY где возможно). (−) Performance overhead ~3-5% на point-lookup (acceptable).

**Wave**: `[wave:s21/k1-w1-rls-postgres]`.

---

### ADR-NEW-13: RPACallPolicy — единый wrapper resilience для RPA/CDC/FileWatcher/Webhook/DesktopRPA

**Контекст**. DEEP-RESEARCH 2026-05-20 (B-02): пять разных RPA-подобных компонентов имеют разрозненную resilience-стратегию:
- `services/rpa/browser_pool.py` — own retry-loop (5 attempts, fixed backoff);
- `infrastructure/sources/cdc.py` — tenacity retry без breaker;
- `infrastructure/sources/filewatcher.py` — no retry, no DLQ;
- `entrypoints/webhook/scheduler.py` — own retry-policy (3 attempts);
- `services/rpa/desktop_rpa.py` — no retry-policy.

Это нарушает Single Entry V22 (`ResilienceCoordinator` class). Невозможно централизованно задать budget / breaker-state / DLQ-routing. Operations team не имеет единого dashboard для RPA resilience.

**Решение**. Создать `core/resilience/rpa_policy.py::RPACallPolicy` — единый wrapper:
```python
class RPACallPolicy:
    def __init__(self, name: str, max_attempts: int, backoff: BackoffStrategy,
                 breaker: CircuitBreaker, dlq_writer: DLQWriter): ...
    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T: ...
```
Композирует:
- `tenacity` retry (S2 unification);
- `pybreaker` breaker (S16 W10 carryover);
- DLQ через `core/messaging/outbox.py` (S2 K2 W3) с `kind=rpa_failure`;
- Audit-event `rpa.call.{attempt|success|failure|breaker_open}`.

Все 5 компонентов миграция на `RPACallPolicy.call(...)`. Feature-flag `RPA_RESILIENCE_WRAPPER_ENABLED` (default-OFF в S21 backbone).

**Обоснование**. Единый Single Entry для RPA resilience. Operations dashboard — один `/admin/circuit-breakers` (S22 F-02) covers все RPA. Bench: 5 toxiproxy сценариев в `tests/resilience/test_rpa_policy.py` (network partition / slow response / connection refused / TLS handshake fail / HTTP 5xx burst).

**Последствия**. (+) Centralization V22 для RPA. (+) Operations visibility единая. (+) DLQ routing для всех RPA-failures. (−) Миграция 5 компонентов (~3-4 дня). (−) ABI breaking — если extensions/* напрямую импортируют `browser_pool.acquire`, нужна wrapper-обёртка с deprecated warning.

**Wave**: `[wave:s21/k2-w1-rpa-resilience-wrapper]`.

---

### ADR-NEW-14: Workflow State Persistence — SQLite (LiteTemporal) + Temporal Cloud (production)

**Контекст**. DEEP-RESEARCH 2026-05-20 (B-05, A-04): `infrastructure/workflow/lite_temporal_backend.py` (S16 W14 OE-3 simplified до 76 LOC) хранит in-flight workflow state **только в памяти**. Под dev_light это нормально, но:
- Worker crash → потеря state всех in-flight workflows (rerun из начала).
- Saga compensating state теряется → orphan compensations.
- В production Temporal Cloud хранит state в своей БД, но нет explicit `WorkflowState` модели для compensating actions (rollback events не персистированы как first-class entities).

**Решение**. Два пути:
1. **LiteTemporalBackend (dev_light)**: `aiosqlite` persistence для in-flight workflow state.
   ```python
   class LiteSQLitePersistence:
       async def save_state(self, wf_id: str, state: dict) -> None: ...
       async def load_state(self, wf_id: str) -> dict | None: ...
       async def delete_state(self, wf_id: str) -> None: ...
   ```
2. **Production Temporal Cloud**: `infrastructure/workflow/saga_state.py::WorkflowState` SQLAlchemy model (PostgreSQL table) для saga compensating state:
   ```python
   class WorkflowState(Base):
       workflow_id: Mapped[str]
       run_id: Mapped[str]
       step_index: Mapped[int]
       compensating_actions: Mapped[list[dict]]  # JSON
       state: Mapped[Literal['running', 'completed', 'compensating', 'rolled_back']]
   ```
   Persisted через Temporal `signal_event` activity (saga state checkpoint).

Feature-flag `WORKFLOW_STATE_SQLITE_PERSIST` (default-OFF в S21 backbone). Tests: `tests/workflow/test_state_persistence.py` — 4 crash-recover сценария.

**Обоснование**. Saga durability — обязательное требование banking compliance (no orphan compensations). LiteTemporalBackend persistence нужна для local dev experience (`ctrl+C` не теряет work-in-progress). SQLite — лёгкий, file-based, async через aiosqlite — не добавляет heavy dependency в dev-стек.

**Последствия**. (+) Crash-resilience для dev_light. (+) Saga compensating actions auditable через PG table. (+) Foundation для future "workflow replay" UI. (−) Дополнительная alembic-миграция для `workflow_state` table. (−) Performance overhead на save_state per-step (~5ms p99, acceptable).

**Wave**: `[wave:s21/k3-w3-workflow-state-persist]`.

---

### ADR-NEW-15: Chaos PR-gate (on-PR triggered chaos tests with label)

**Контекст**. DEEP-RESEARCH 2026-05-20 (F-15 follow-up S20 W6): chaos test suite (33 tests, Toxiproxy) запускается только nightly. PR может пройти CI зелёным, но сломать chaos-resilience (например, removing breaker.guard() обёртку). Bug обнаруживается на следующий день в nightly — слишком поздно для PR review.

С другой стороны: chaos suite длится 8-12 минут. Если запускать на каждый PR — CI becomes slow и draining для contributor. Нужен compromise.

**Решение**. PR-gate на label. `.github/workflows/chaos-gate.yml`:
```yaml
on:
  pull_request:
    types: [labeled, synchronize]
jobs:
  chaos:
    if: contains(github.event.pull_request.labels.*.name, 'needs-chaos')
    steps:
      - run: make chaos
```
Триггеры:
- Reviewer добавляет label `needs-chaos` если PR трогает: `core/resilience/`, `infrastructure/sources/`, `infrastructure/sinks/`, `entrypoints/webhook/`, `services/rpa/`.
- `synchronize` event перезапускает на push в PR с этим label.
- Без label — chaos не запускается (default нагрузка на CI остаётся низкой).

PR-checks становятся required: chaos-gate (когда label present) → блокирует merge при fail.

CI gate label: при отсутствии label в PR на critical paths (above list) — comment-bot пишет "Consider adding `needs-chaos` label for resilience-critical changes."

Feature-flag `CHAOS_CI_PR_GATE` (default-OFF в S23 backbone; flip default-ON после первой недели observation).

**Обоснование**. Compromise между скоростью CI и chaos-resilience guarantees. Required только для PR, которые fact трогают resilience код. Bot-comment educates reviewer'а на правильное использование label.

**Последствия**. (+) Resilience regressions detect at PR-time, не nightly. (+) Не slow-downим CI для not-critical PRs. (+) Comment-bot scaffolds правильную практику. (−) Bypass: reviewer может забыть label → relies on comment-bot reminders. (−) Дополнительный workflow YAML maintenance.

**Wave**: `[wave:s23/k5-w3-chaos-ci-pr-gate]`.

---

## Архитектурные рекомендации V2 GAP-анализа (A-01 → A-07)

Источник: GAP-анализ V2 (`gap-analysis/GAP-ANALYSIS-V2-gd_integration_tools-2026-05-21.md`).
Прошли цикл самокритики: Critic + Devil's Advocate. QUALITY_SCORE: 74/100.

### ADR-A-01: RouteMiddlewareSpec dataclass для декларативной композиции middleware

**Контекст.** L1 Gateway: middleware chain жёстко закодирована в `setup_middlewares.py`.
Нет единого объекта контекста запроса. Per-route override невозможен без edit ядра.

**Решение.** Ввести dataclass:
```python
@dataclass
class RouteMiddlewareConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    overrides: dict[str, dict] = field(default_factory=dict)
```
route.toml:
```toml
[middleware]
include = ["rate_limit", "auth", "audit"]
exclude = ["data_masking"]
overrides.rate_limit = { limit = 1000, window = "1m" }
```
`MiddlewareRegistry` читает конфиг → строит цепочку.

**Обоснование.** Декларативность без переписывания ядра. Plugin-agnostic.
Роууты остаются auth-агностичными. Middleware chain визуализируема.

**Прошёл_самокритику:** Да (Адвокат D1: не оверинжиниринг — упрощает конфигурацию).

**Wave**: `[wave:s17/k3-w2-middleware-registry]`.

---

### ADR-A-02: Plugin hot-swap V2 — per-plugin shutdown

**Контекст.** L2 Core: `hot_swap.py:213` `loader.shutdown_all()` убивает ВСЕ плагины.
B-04 критический блокер. Hot-reload одного плагина невозможен.

**Решение.** Заменить `shutdown_all()` на:
```python
async def hot_swap_plugin(self, plugin_id: str) -> None:
    # 1. Graceful drain: accept no new requests
    # 2. Wait for in-flight (with timeout)
    # 3. shutdown_plugin(plugin_id) — только один
    # 4. reload + register
    # 5. Other plugins unaffected
```

**Обоснование.** Изоляция failure domain. Независимые lifecycle per plugin.

**Прошёл_самокритику:** Да (Адвокат D4: B-04 остаётся блокером, shutdown_all() — реальный риск).

**Wave**: `[wave:s19/k3-w6-plugin-hot-swap-v2]`.

---

### ADR-A-03: TenantNamespacedCache integration — подключить к существующим адаптерам

**Контекст.** L6 Data: `core/tenancy/cache.py::TenantNamespacedCache` (96 LOC) СУЩЕСТВУЕТ.
Проблема: `redis_cluster.py` и `s3_cache.py` НЕ используют tenant key prefix.
B-03 критический — данные тенантов могут пересекаться в кэше.

**Решение.** Добавить wrapper-слой в адаптеры:
```python
class TenantAwareRedisCache:
    def __init__(self, delegate: RedisCache, tenant_ctx: TenantContext):
        self.delegate = delegate
        self.tenant = tenant_ctx

    async def get(self, key: str) -> Value | None:
        return await self.delegate.get(f"{self.tenant.id}:{key}")
```
Аналогично для S3Cache.

**Обоснование.** Infrastructure уже есть. Integration task, не архитектурное изменение.
Минимальный risk, high impact.

**Прошёл_самокритику:** Да (Критик NK-03: подтвердил существование TenantNamespacedCache).

**Wave**: `[wave:s21/k1-w2-tenant-cache-wrapper]`.

---

### ADR-A-04: Workflow state persistence — Temporal persistence для LiteTemporalBackend

**Контекст.** L6 Data: LiteTemporalBackend (stub) не персистит workflow state.
B-05 критический. In-flight workflows теряются при crash.

**Решение.** Подключить persistence к LiteTemporalBackend:
```python
# LiteTemporalBackend с persistence
class LiteTemporalBackend:
    async def save_state(self, run_id: str, state: dict) -> None:
        async with aiofiles.open(f".temporal/{run_id}.json", "w") as f:
            await f.write(json.dumps(state))

    async def load_state(self, run_id: str) -> dict | None:
        try:
            async with aiofiles.open(f".temporal/{run_id}.json") as f:
                return json.loads(await f.read())
        except FileNotFoundError:
            return None
```

**Обоснование.** Crash-resilience для development. Foundation для future workflow replay UI.

**Прошёл_самокритику:** Да (Адвокат D4: B-05 остаётся блокером, LiteTemporalBackend = operator error).

**Wave**: `[wave:s21/k3-w3-workflow-state-persist]`.

---

### ADR-A-05: RPA resilience wrapper — @policy decorator над RPA/CDC

**Контекст.** L5 RPA: resilience infrastructure (CircuitBreaker, Retry, Bulkhead, Timeout)
ЕСТЬ, но не применяется к RPA и CDC. B-02 критический — события теряются.

**Решение.** Ввести decorator:
```python
@policy(
    retries=Retry(attempts=3, backoff=exponential),
    circuit_breaker=CircuitBreaker(failure_threshold=5),
    timeout=Timeout(seconds=30),
)
async def rpa_action(exchange: Exchange) -> Exchange:
    ...
```
Применяется к: `browser_pool.py`, `cdc.py:497`, `file_watcher.py`, `webhook_scheduler.py`.

**Обоснование.** Zero architectural change. Resilience уже есть — только wire up.

**Прошёл_самокритику:** Да (Шина-эксперт: CDC event loss подтверждён).

**Wave**: `[wave:s21/k2-w1-rpa-resilience-wrapper]`.

---

### ADR-A-06: SecurityHeadersMiddleware → чистый ASGI middleware

**Контекст.** L8 Security: `security_headers.py` наследует `BaseHTTPMiddleware`.
B-07 — race condition: заголовки применяются после ASGI-цепочки.

**Решение.** Переписать как чистый ASGI-app:
```python
class SecurityHeadersMiddleware:
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(SECURITY_HEADERS)
            await send(message)

        await self.app(scope, receive, send_with_headers)
```

**Обоснование.** Исправляет race condition. 50-80 LOC. ASGI-native.

**Прошёл_самокритику:** Да (Критик CD-07: подтверждена race condition).

**Wave**: `[wave:s22/k1-w1-security-headers-asgi]`.

---

### ADR-A-07: PII masker unification — DataMaskingMiddleware → mask_all()

**Контекст.** L8 Security: DataMaskingMiddleware не использует `core/security/pii_masker.py::default_masker()`
(8 типов PII: email, phone, INN, SNILS, passport, card). B-06 критический.

**Решение.** Переписать middleware на использование существующего masker:
```python
class DataMaskingMiddleware:
    def __init__(self, app, masker: PIIMasker = None):
        self.app = app
        self.masker = masker or default_masker()

    async def __call__(self, scope, receive, send):
        # Read and mask response body using self.masker.mask_all(value, pii_type)
```

**Обоснование.** Infrastructure уже есть (8 типов PII). Middleware не использует.
Unification = 20-30 LOC diff.

**Прошёл_самокритику:** Да (Критик CD-06: подтверждено).

**Wave**: `[wave:s22/k1-w2-pii-masker-unify]`.