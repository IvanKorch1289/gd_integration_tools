# Cycle 1 — Phase 2 — Сводный отчёт по 12 доменам

> **Дата:** 2026-08-06
> **HEAD:** `7f3d94a3`
> **Cycle:** 1 (post-Sprint 184)
> **Baseline:** layer-allowlist 180 строк, pip-audit allowlist 79 строк (35 active CVE),
> working tree с pre-existing modifications от прошлого спринта.

---

## 1. Сводная таблица готовности по 12 доменам

| # | Домен | % | P0 | P1 | P2 | P3 | P4 | Обоснование |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **A1** | Infrastructure | **82** | 1 | 2 | 4 | 3 | 2 | DLQ+CDC pool ok, B-25 silent loss в AuditEventLog |
| **A2** | Security | **78** | 2 | 2 | 3 | 1 | 1 | WAF coverage gate FAIL (sms_sink), OtelMiddleware concurrency bug |
| **A3** | Services | **73** | 2 | 3 | 9 | 5 | 0 | Admin fail-OPEN, ClickHouse silent_loss, DQSeverity dedup, dead @service_dsl |
| **A4** | Entrypoints | **95** | 0 | 1 | 3 | 3 | 2 | Pure ASGI 26/27, multi-protocol, **только 1 P1** (ObservabilityMW legacy) |
| **A5** | API-Contracts | **75** | 1 | 3 | 2 | 2 | 1 | schema-registry `dict[str, Any]` fallback (D-A5-01 P0) |
| **A6** | DSL-Route-Workflow-Service | **80** | 1 | 3 | 3 | 2 | 1 | `.then()` broken в orders_dsl.py (cross A8) |
| **A7** | DSL-Engine-Processors | **65** | 2 | 9 | 12 | 6 | 0 | security.py deprecated import, 442 LOC dead `eip/reliability.py`, only 22/270 registered |
| **A8** | Workflow-Temporal | **25** | **6** | 5 | 10 | 8 | 4 | **TemporalWorkerPool unwired**, ActivityBridge.decorate() ни разу не вызван, 4 processors без @processor |
| **A9** | Agents-AI-RAG | **66** | 3 | 6 | 11 | 6 | 5 | RAG PII fail-open, dead RagCachePrewarmer, hardcoded tenant_id |
| **A10** | Business-Logic-Extensions-Routes | **77** | 4 | 2 | 2 | 2 | 0 | 4 broken YAML call_function refs, 3 NEW layer violations |
| **A11** | Dependencies-Supply-Chain | **35** | **5** | 5 | 3 | 3 | 0 | **FAIL-OPEN gate через пустой pip-audit.json**, SBOM устарел, test FAILED |
| **A12** | Config-Environment-Ops | **78** | 2 | 5 | 8 | 6 | 5 | **docker-compose без mem_limit/cpus верифицировано** (гипотеза #1 confirmed) |

**Средневзвешенная готовность:** **(82+78+73+95+75+80+65+25+66+77+35+78)/12 ≈ 69.0%**

**Распределение:**
- **≥80%:** A1 (82), A4 (95), A6 (80) — 3 домена
- **70-79%:** A2 (78), A3 (73), A5 (75), A9 (66→low), A10 (77), A12 (78) — 5-6 доменов
- **<70%:** A7 (65), A8 (25), A9 (66), A11 (35) — 4 домена

**Стоп-критерий (≥80% по ВСЕМ 12 доменам + 3 PASS + allowlist не растёт): НЕ ВЫПОЛНЕН**

Только 3/12 доменов достигают 80%. Необходим повторный цикл.

---

## 2. Список P0 находок (cross-domain)

### P0 — data-loss / security (блокирующие)

| ID | Домен | Файл:строка | Описание |
|---|---|---|---|
| **B-25** | A1 | `infrastructure/audit/event_log.py:112-113` | `_flush_to_clickhouse` silent loss (только logger.error, нет DLQ) |
| **D-A2-01** | A2 | `infrastructure/sinks/sms_sink.py:109,158` | `httpx.AsyncClient` напрямую, обходит WAF — coverage gate FAIL |
| **D-A2-02** | A2 | `extensions/osint_agent/functions/osint_workflow.py:234` | Тот же pattern вне WAF-gate scope |
| **D-A3-01** | A3 | `services/admin/api.py:97-102` | Admin **fail-OPEN** при AuthZ unavailable (privilege-escalation vector) |
| **D-A3-02** | A3 | `services/audit/clickhouse_audit_service/service.py:220-223` | Audit silent_loss без `_logger.critical` + metric |
| **D-A5-01** | A5 | `services/schema_registry/registry.py:251-270` | `dict[str, Any]` fallback для unregistered schemas |
| **D-A7-01** | A7 | `security.py:52` | Импортирует из DEPRECATED shim'а `_VERIFIERS` — fail-closed |
| **D-A7-02** | A7 | `external.py` | Дубль `MCPToolProcessor`/`AgentGraphProcessor` shadowed by `agent_dsl/*` |
| **D-A8-01** | A8 | `core/config/features/workflow.py:32-72` | **WorkflowFlags docstring lie**: 4/5 default=True, docstring обещает OFF |
| **D-A8-02** | A8 | `dsl/engine/processors/workflow/*.py` + `best_practices/*.py` | **4 процессора без `@processor()`** — capability-check никогда не срабатывает |
| **D-A8-03** | A8 | `dsl/workflow/compiler/activity_bridge.py:288-305` + `infrastructure/workflow/worker.py:1-418` | **`ActivityBridge.decorate()` + `TemporalWorkerPool` ни разу не вызваны** — production worker использует ТОЛЬКО pg-runner |
| **D-A8-04** | A8 | `infrastructure/workflow/temporal_client.py:227-321` | **`TemporalWorkerPool` не инстанцируется** (94 LOC, 0 call-sites) |
| **D-A8-05** | A8 | `plugins/composition/workflow_setup.py:76-83` | `_bootstrap_default_declarations` импортирует несуществующие `orders_saga.py`/`payments_saga.py` |
| **D-A8-06** | A8 | `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,316,326,336` | **`orders_dsl.py` использует несуществующий `.then()`** (6 мест) |
| **D-A9-184-1** | A9 | services/ai/rag/api.py | RAG PII fail-open на single-doc API |
| **D-A9-184-2** | A9 | services/ai/rag/ | dead `RagCachePrewarmer` |
| **D-A9-184-3** | A9 | extensions/osint_agent | hardcoded tenant_id/correlation_id |
| **D-A9-184-4** | A9 | entrypoints/mcp/fastmcp_server.py | layer violation |
| **B-101** | A10 | `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml` | references 2 non-existent functions (`fetch_for_workflow`, `emit_decision`) |
| **B-102** | A10 | `routes/hello_route/main.dsl.yaml` | references non-existent `extensions.hello_route.normalizer` |
| **B-103** | A10 | `routes/test_route_w1/main.dsl.yaml` | references non-existent `extensions.test_route_w1.normalizer` |
| **D-A10-100** | A10 | `extensions/{core_admin,dadata,skb}/plugin.toml` | 3 plugins have `entry_class → SchemasOnlyEntry` (empty class, not BasePlugin) |
| **D-AUDIT-11-1** | A11 | `tools/pip_audit_gate.py:26-32` + `pip-audit.json` (0 bytes) | **FAIL-OPEN security gate**: пустой JSON → gate PASS |
| **D-AUDIT-11-2** | A11 | `dist/sbom.cdx.json` | **SBOM устарел** (cryptography 41.0.7 vs uv.lock 49.0.0) |
| **D-AUDIT-11-3** | A11 | `tests/unit/tools/test_supply_chain_scaffold.py:22,75` | **Тест FAILED** (`Makefile.security` не существует) |
| **D-AUDIT-11-4** | A11 | `make/security.mk:45-57` | **`make audit-deps` НЕ создаёт `pip-audit.json`** |
| **D-AUDIT-11-5** | A11 | make + generate_sbom.py + check_supply_chain.py | **3-way SBOM paths drift** |
| **D-A12-01** | A12 | `core/config/hot_reload.py:39-41` | **Hot-reload НЕ подключён в production** (только в docstring) |
| **D-A12-02** | A12 | `config_loader.py:273-303,347-353` | **ConsulConfigSettingsSource = dead code** (НЕ включён в settings_customise_sources) |

**Итого P0: 29 уникальных находок.**

---

## 3. Список P1 находок (cross-domain) — top-15

| ID | Домен | Описание |
|---|---|---|
| **D-AUDIT-A1-1** | A1 | ListenNotifyCDCBackend SCAFFOLD (`_stopped.wait()` без `asyncpg.connect`) |
| **D-AUDIT-A1-2** | A1 | PollCDCBackend polling-mode SCAFFOLD (`if False: yield CDCEvent`) |
| **D-A2-03** | A2 | `entrypoints/middlewares/otel_middleware.py:125-126` — concurrency bug |
| **D-A2-04** | A2 | `ObservabilityMiddleware` на `BaseHTTPMiddleware` |
| **D-A2-05** | A2 | `DeprecationMiddleware` на `BaseHTTPMiddleware` |
| **D-A3-03** | A3 | `services/ops/data_quality/` 4-way duplication `DQSeverity`/`DQViolation`/`DQCheckResult`/`DQRule` |
| **D-A3-04 / D-A3-05** | A3 | services → extensions reverse-layer shims |
| **D-A3-06** | A3 | `@service_dsl`/`@register_action` decorators — 0 usage, 156 LOC dead |
| **D-A4-01** | A4 | `ObservabilityMiddleware` на `BaseHTTPMiddleware` (cross A2 D-A2-04) |
| **D-A6-02** | A6 | `_bootstrap_default_declarations` импортирует несуществующие модули (cross A8 D-A8-05) |
| **D-A7-04** | A7 | 442 LOC legacy `eip/reliability.py` — DEAD, shadowed by package directory |
| **D-A7-08** | A7 | Только 22 из ~270+ processors зарегистрированы через `@processor` |
| **D-A7-09** | A7 | `fs_directory_scan.py` 247 LOC DEPRECATED shim |
| **D-A8-07** | A8 | `compile_guardrail_step` fail-open для non-numeric (cost explosion в banking context!) |
| **D-A8-08** | A8 | Multi-tenant namespace mismatch warning-only |

---

## 4. Глобальные находки (cross-domain)

### 4.1 Рост layer-violations allowlist (RESIDUAL)
- Baseline: 180 строк (`tools/check_layers_allowlist.txt`)
- Это +5 за сутки с 173. **Тренд — рост, не снижение** (заявленная цель 174→100 не выполняется).
- Новые нарушения: A10 (3 extensions → core-only rule broken через `src.backend.dsl.*`).
- 5 lazy-imports infrastructure → services (4 в allowlist, 1 не верифицировано).

### 4.2 35 CVE в pip-audit allowlist (RESIDUAL)
- `.security/pip-audit-allowlist.txt` — 79 строк, 35 active CVE.
- 8 stale CVE (installed ≥ fix-version, но всё ещё listed) — RESIDUAL от cycle-3 DEPS-P0-001.
- 4-way CVE drift (GitHub=2, GitLab=1, pip_audit_gate.py=1, Makefile=35).
- Новые CVE от доработок **не блокируются** — fail-open gate через пустой JSON.

### 4.3 Дубли процессоров (S35 vs M6 vs M7)
- `FileListProcessor` (M6) vs `DirectoryScanProcessor` (S35) vs `FilteredDirectoryScanProcessor` (M7) —
  3 файловых scanner-процессора с частичным пересечением семантики.
- `BpmnImportNotAvailableError` (A8) — dead exception.
- `_VERIFIERS` shim в `security.py:52` (A7) — ссылается на удалённый модуль.

### 4.4 Неконсистентные capability-декларации
- 4 процессора без `@processor()` decorator (A8) — capability-check не срабатывает.
- 3 plugins с `entry_class → SchemasOnlyEntry` (A10) — пустой класс, не BasePlugin.
- WorkflowFlags 4/5 default=True (A8) vs docstring обещает OFF.

### 4.5 4-way CVE drift (A11)
- `.security/pip-audit-allowlist.txt` (35, canonical)
- `make/security.mk` (35, dynamic read)
- `.github/workflows/security.yml` (2 hardcoded)
- `.gitlab/ci/.gitlab-ci.yml` (1 hardcoded)
- `tools/pip_audit_gate.py` (1 hardcoded — `PYSEC-2026-87`)

### 4.6 3-way SBOM paths drift (A11)
- `make/security.mk:sbom` → `dist/sbom.cdx.json`
- `tools/checks/generate_sbom.py` → `dist/sbom/sbom.cdx.json`
- `tools/checks/check_supply_chain.py:run_sbom` → `dist/sbom/`

### 4.7 Fail-open gate через пустой pip-audit.json (A11)
- `pip-audit.json` существует, но 0 bytes.
- `tools/pip_audit_gate.py` парсит JSON, видит `dependencies = []`, **возвращает PASS**.
- Если CI не пересоздаёт файл через `pip-audit --output` → gate всегда PASS.

### 4.8 docker-compose без resource limits (A12, гипотеза #1 confirmed)
- **ВЕРИФИЦИРОВАНО:** ни в одном из 6 docker-compose файлов (`docker-compose.yml`,
  `docker-compose.prod.yml`, `docker-compose.light.yml`, `docker-compose.perf.yml`,
  `docker-compose.bluegreen.yml`, `docker-compose.windows-worker.yml`) НЕТ `mem_limit`/`cpus`/`deploy.resources`.
- K8s manifests имеют `resources: limits/requests` для CPU/memory — дисциплина не распространена на dev-compose.
- Production compose-stack (`docker-compose.prod.yml:225-247`) — отсутствует healthcheck на `app` (D-A12-06 P1).

### 4.9 Hot-reload не подключён в production (A12)
- `reloader.watch()` вызывается только в docstring-примерах `hot_reload.py:39-41`.
- Документация `SETTINGS_GUIDE.md:67` и `HOT_RELOAD.md:55-61` явно описывают этот gap.

### 4.10 ConsulConfigSettingsSource = dead code (A12)
- Определён в `config_loader.py:273-303`, но НЕ включён в `settings_customise_sources` (config_loader.py:347-353).
- Consul integration для runtime-config не работает.

---

## 5. Явные противоречия между отчётами разных доменов

### 5.1 A8 vs A6: dual-mode DSL — OK или broken?
- A6: "DSL dual-mode (Python ↔ YAML) — 80% готовности, WorkflowBuilder 17+ методов"
- A8: "6 P0: WorkflowFlags lie, 4 processors без @processor(), ActivityBridge.decorate() ни разу не вызвана, TemporalWorkerPool unwired, _bootstrap_default_declarations imports несуществующих модулей, orders_dsl.py использует .then() метод которого нет"
- **Совместимо:** DSL dual-mode работает на уровне schema+compile, но **Temporal Worker runtime path мёртв**.
- **Решение:** A6 OK на syntactic level, A8 фиксирует runtime fragility.

### 5.2 A11 vs A1: pre-flight gate и layer-checker — оба утверждают "OK"
- A1: "0 новых layer violations, baseline 175 legacy"
- A11: "test_supply_chain_scaffold FAILED" (D-AUDIT-11-3 P0)
- **Совместимо:** layer-checker и supply-chain scaffold test — независимые проверки.
- **Реальность:** обе могут быть верны; layer-disciplne стабильна, supply-chain test infrastructure имеет drift.

### 5.3 A8 vs A12: WorkflowFlags — config drift
- A12: "94 Pydantic-settings файлов, единая точка `settings_customise_sources`"
- A8: "WorkflowFlags 4/5 default=True, docstring обещает OFF"
- **Решение:** A12 общее правило соблюдено, но **конкретный** `core/config/features/workflow.py:32-72` нарушает конвенцию проекта.

### 5.4 A4 vs A2: 2 middleware на BaseHTTPMiddleware
- A4: "26/27 middleware на pure ASGI, **1 на BaseHTTPMiddleware**: ObservabilityMiddleware"
- A2: "ObservabilityMiddleware + DeprecationMiddleware на BaseHTTPMiddleware" (2 middleware)
- **Совместимо:** A4 фиксирует ObservabilityMiddleware (cycle 56), A2 фиксирует оба (Observability + Deprecation).
- **Реальный счёт:** 2 middleware на legacy framework (требуется fix).

### 5.5 A7 vs A8: P0 processors без @processor()
- A7: "только 22 из ~270+ processors зарегистрированы через `@processor`"
- A8: "4 processors без `@processor()`: workflow_subprocess, workflow_convert, claim_check, continue_as_new"
- **Совместимо:** A7 даёт общую статистику (8% coverage), A8 даёт конкретный список 4.

### 5.6 A9 vs A10: extensions/osint_agent layer violation
- A9: "fastmcp_server layer violation (D-A9-184-4)"
- A10: "extensions/osint_agent входит в scope extensions audit"
- **Решение:** разные файлы — оба валидны.

---

## 6. Глобальные тренды

### Домены ≥80% готовности (3 из 12)
- **A4 (95%)** — Entrypoints: production-ready, 1 P1 (ObservabilityMW legacy)
- **A1 (82%)** — Infrastructure: production-ready для CDC/ClickHouse, 1 P0 (AuditEventLog silent loss)
- **A6 (80%)** — DSL-Route-Workflow-Service: declarative OK, runtime fragile (cross A8)

### Домены 70-79% (5 из 12)
- **A2 (78%)** — Security: WAF gate FAIL (2 P0), 2 middleware legacy
- **A3 (73%)** — Services: admin fail-OPEN (P0), DQSeverity dedup (P1), dead @service_dsl (P1)
- **A5 (75%)** — API-Contracts: schema-registry dict fallback (P0)
- **A10 (77%)** — Business-Logic: 4 broken YAML refs (P0), 3 NEW layer violations
- **A12 (78%)** — Config-Ops: hot-reload missing (P0), docker-compose без limits (P1 confirmed)

### Домены <70% (4 из 12)
- **A7 (65%)** — DSL-Engine-Processors: 442 LOC dead reliability, 22/270 registered
- **A8 (25%)** — Workflow-Temporal: 6 P0 PERSISTS (TemporalWorkerPool unwired!)
- **A9 (66%)** — Agents-AI-RAG: 3 P0 (RAG PII fail-open, dead prewarmer, hardcoded tenant_id)
- **A11 (35%)** — Dependencies-Supply-Chain: 5 P0 (FAIL-OPEN gate!)

---

## 7. Решение по доменам

### Домены, требующие отдельного цикла/приоритизации
- **A8 (Workflow-Temporal)**: 6 P0 PERSISTS, требует dedicated cycle для Temporal Worker runtime
- **A11 (Dependencies)**: 5 P0 + fail-open security gate — блокирует production sign-off
- **A7 (DSL-Engine-Processors)**: 442 LOC dead + 22/270 registered → требует cleanup PR

### Домены, готовые к Phase 3 (quick-fix)
- **A4 (Entrypoints)**: 1 P1 fix (ObservabilityMW migrate to pure ASGI)
- **A1 (Infrastructure)**: 1 P0 fix (AuditEventLog silent loss)
- **A6 (DSL-Route-Workflow-Service)**: 1 P0 fix (.then() alias)

### Домены, требующие глубокого планирования
- **A8, A11, A7** — dedicated tasks с task DAG + критерии готовности
- **A2, A3, A5** — несколько P0 + комплексные fix-ы

---

## 8. Домены <80% — что нужно для достижения 80%

### A7 (65% → 80%, +15%)
1. Закрыть D-A7-01 (security.py deprecated import) — fix импорт, переписать fail-closed через Pydantic
2. Закрыть D-A7-02 (MCPToolProcessor shadow) — rename или удалить дубль
3. Удалить 442 LOC `eip/reliability.py` — deprecated package directory
4. Зарегистрировать 4 priority processor'а через `@processor()`

### A8 (25% → 80%, +55%)
1. Закрыть 6 P0: WorkflowFlags default=False, 4 @processor(), ActivityBridge wire, TemporalWorkerPool runtime, .then() alias, _bootstrap import fix
2. Закрыть 5 P1: guardrail fail-open, namespace raise, WorkflowHandle, sensor cap, WatchError cap
3. Итог: ~70% после P0+P1, +dead code cleanup (~10%) → ~80%

### A9 (66% → 80%, +14%)
1. Закрыть 3 P0: RAG PII fail-open, RagCachePrewarmer removal, hardcoded tenant_id
2. Закрыть 4 из 6 P1: dead skill_registry, get_ai_agent_service NotImplemented, duplicate LiteLLMModel, layer violations

### A11 (35% → 80%, +45%)
1. Закрыть 5 P0: pip_audit_gate empty JSON exit 1, SBOM regen, test fix, --output в make, SBOM paths unify
2. Закрыть 5 P1: 8 stale CVE, 4-way drift, streamlit upper bound, misleading comments, IGNORED_VULNS
3. Итог: ~65-70% после P0+P1, +3 P2 cleanup → ~75-80%

### A3 (73% → 80%, +7%)
1. Закрыть 2 P0: admin fail-CLOSED, ClickHouseAuditService silent_loss metric
2. Закрыть 3 P1: DQSeverity dedup, reverse-layer shims, @service_dsl decorators migrate

### A2 (78% → 80%, +2%)
1. Закрыть 2 P0: sms_sink WAF, osint_agent WAF
2. Закрыть 2 P1: OtelMiddleware concurrency, ObservabilityMW+DeprecationMW migrate

### A5 (75% → 80%, +5%)
1. Закрыть 1 P0: schema-registry TypedAdapter wrapper

### A10 (77% → 80%, +3%)
1. Закрыть 4 P0: 4 broken YAML call_function refs

### A12 (78% → 80%, +2%)
1. Закрыть 2 P0: hot-reload production wire, ConsulConfigSettingsSource integrate

---

## 9. Топ-3 next-task для каждой категории фиксов

### Безопасность/надёжность (P0)
1. **A11 — D-AUDIT-11-1**: fail-open gate fix (`tools/pip_audit_gate.py`) — 30 мин, exit 1 на empty JSON
2. **A2 — D-A2-01**: `sms_sink.py` WAF coverage fix — 1 час, через `core/net/waf_facade`
3. **A8 — D-A8-02**: 4 processors зарегистрировать через `@processor()` — 30 мин, +24 LOC

### Архитектурные границы (P1)
1. **A4 — D-A4-01**: ObservabilityMW migrate to pure ASGI — 2 часа, фиксирует legacy
2. **A11 — D-AUDIT-11-7**: 4-way CVE drift unify — 2 часа, single source of truth
3. **A12 — D-A12-04**: docker-compose resource limits — 1 час, добавить mem_limit/cpus в 6 файлов

### Мёртвый код (P2)
1. **A7 — D-A7-04**: удалить 442 LOC `eip/reliability.py` — 15 мин
2. **A8 — D-A8-15**: удалить `ContinueAsNewHandler` + `WorkflowContinueAsNewProcessor` — 30 мин, −400 LOC
3. **A3 — D-A3-06**: удалить 156 LOC dead `@service_dsl`/`@register_action` decorators — 15 мин

### Замена кастомного кода библиотеками (P3)
1. **A1 — D-AUDIT-A1-12**: `prometheus-fastapi-instrumentator` workaround → `starlette-exporter` — −100-200 LOC
2. **A8 — D-A8-23**: `WorkflowSubprocessProcessor` + BPMN importer → `spiffworkflow` — −300 LOC
3. **A9**: `LlmGuard` vs custom OWASP regex — замена кастомного regex через `llm-guard` library

### Новые фичи (P4) — только где обосновано
1. **A8 — D-A8-31/32/33**: cron/schedule DSL, parallel() fan-out, with_timeout per-step — обосновано для Camel/Airflow/Temporal parity
2. **A9**: DSPy MIPROv2 prompt optimization — обосновано для RAG cost reduction (saving ~30% token cost)
3. **A8 — D-A8-34**: TemporalWorkflowBackend.start_child_workflow — обосновано для HITL pattern в banking

---

## 10. Финальная оценка cycle-1

### Метрики
| Показатель | Значение |
|---|---|
| Доменов ≥80% | **3 / 12** (A1, A4, A6) |
| Доменов 70-79% | 5 / 12 (A2, A3, A5, A10, A12) |
| Доменов <70% | 4 / 12 (A7, A8, A9, A11) |
| Всего P0 | **29** |
| Всего P1 | ~50 |
| Layer-allowlist (target ≤178) | **180** (RESIDUAL +5 vs cycle baseline) |
| pip-audit allowlist | 79 строк / 35 active CVE (RESIDUAL, не заблокировано) |

### Стоп-критерий: **НЕ ВЫПОЛНЕН**

- ✗ Только 3/12 доменов ≥80% (требуется ВСЕ 12)
- ✗ layer-allowlist не снизился (180 ≥ baseline 180, тренд роста RESIDUAL)
- ✓ Новых CVE от доработок не появилось (cycle 1 не вносил deps)
- ? Ревью Phase 5 не выполнялось (Phase 2 → 3 → 4 → 5 в очереди)

### Вердикт: **Требуется повторный цикл**

**Cycle 2 должен:**
1. Закрыть 6 P0 в A8 (Temporal Worker runtime) — самый критичный блокер
2. Закрыть 5 P0 в A11 (supply-chain fail-open gate)
3. Закрыть 2 P0 в A7 (security.py deprecated import, MCPToolProcessor shadow)
4. Закрыть 4 P0 в A10 (broken YAML refs)
5. Закрыть 2 P0 в A1 + A12 (AuditEventLog silent loss + hot-reload)
6. Закрыть 2 P0 в A2 (WAF coverage)
7. Закрыть 2 P0 в A3 (admin fail-CLOSED, audit silent_loss)
8. Закрыть 1 P0 в A5 (schema-registry TypedAdapter)
9. Закрыть 1 P0 в A6 (.then() alias — cross A8 D-A8-06)
10. Закрыть 3 P0 в A9 (RAG PII fail-open, dead prewarmer, hardcoded tenant_id)

После этого cycle-2 должен достичь 80% по 8-10 доменам, и cycle-3 закроет остаток.

---

## 11. Cross-domain запросы к Phase 3 architect

1. **A8 → A1, A3, A4**: какой backend использовать в production — Temporal или pg-runner? ADR-045 обещает Temporal default, но production worker использует pg-runner.
2. **A11 → A12**: кто владеет SBOM pipeline (Makefile target vs tools/checks/generate_sbom.py vs check_supply_chain.py)?
3. **A7 → A8**: dead `eip/reliability.py` (442 LOC) shadowed by `eip/reliability/` package — cleanup PR?
4. **A2 → A11**: WAF coverage allowlist — кто поддерживает canonical список?
5. **A10 → A3**: extensions/{core_admin,dadata,skb} `entry_class → SchemasOnlyEntry` — это норма для schema-only плагинов или regression?

---

## 12. Заключение

**Cycle 1 аудит завершён.** Стоп-критерий не выполнен — только 3/12 доменов ≥80%.

**Критические блокеры cycle 2:**
- A11 fail-open security gate (production sign-off заблокирован)
- A8 Temporal Worker runtime мёртв (6 P0 PERSISTS)
- A7/A10 многочисленные P0

**Рекомендуемый focus для cycle 2:**
- 80% effort на P0 fixes (29 находок)
- 15% effort на P1 architecture boundaries
- 5% effort на dead code cleanup

Phase 3 architect должен создать task DAG с явными критериями "готово" для каждого P0+P1.
