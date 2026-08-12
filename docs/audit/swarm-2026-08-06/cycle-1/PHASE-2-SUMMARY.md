# Cycle 1 · Phase 2 — Summary (evidence-preserving)

**Дата:** 2026-08-06
**Baseline:** `b69d6b49bc62918a02e47dc20ab81615fd8500b1`
**HEAD:** `2f620910951a727f50d4539b998375b0c0bda55d` (1 коммит поверх baseline: S183 W2 #1, S3 multipart abort)
**Автор:** Phase 2 summarizer (read-only агент)
**Источник:** `docs/audit/swarm-2026-08-06/cycle-1/BASELINE.md` + 12 отчётов из `phase-1/01..12-*.md`. Другие артефакты (source, git diff/log, CLAUDE/PLAN/KNOWN_ISSUES, долги) — НЕ читал.

> **Честная оговорка по числам.** Агенты использовали **12 разных формул readiness**
> (см. §5 / §10). Числа в отчётах несопоставимы; ниже они приводятся **только как
> self-assessment** каждого аналитика. Суммы по доменам и нормализованный реестр
> findings собирались напрямую по таблицам отчётов.

---

## 1. Executive Summary

* **12 доменов** прошли Phase 1, каждый со своим self-assessed readiness.
* **Gate-status (агрегировано):** ни один из 12 доменов не достиг self-assessed ≥80.
  Все 12 отчётов применяют правило «оценка ≥80 запрещена при наличии P0/P1», и
  **каждый домен** содержит хотя бы один P0. Поэтому для каждого домена финальная
  цифра — это `min(formula_score, 79)` или просто `0` при clamp.
* **Всего findings:** **213** уникальных записей после нормализации ID (см. §3).
  Распределение: **P0=37**, **P1=57**, **P2=61**, **P3=29**, **P4=29**.
* **Топ-3 консолидированных блокера** (cross-domain corroborations):
  1. **Composition root / startup blockers** — extensions DI (P0-001 в
     `10-business-logic`), saga imports (P0-002 там же), admin fail-open
     (`03-services:P0-001`), admin mock-fallback в destructive ops
     (`05-api:P0-001/P0-002`), dead import `src.backend.workflows.*`
     (`05-api:P0-003`). Любой из них блокирует production startup или
     первый вызов admin-endpoint.
  2. **DLQ bypass на MQ/IMAP/MQTT/filewatcher/scheduler** — единая инфра
     DLQ envelope существует (`01-infrastructure` STR), но MQ-handlers в
     `04-entrypoints:P0-002` логируют и ack'ают вместо enqueue в
     OutboxBackend. Это **data-loss path** при poison-message.
  3. **Capability-gate / fail-open в критических путях** — повторяется в
     6+ доменах: `02-security:P0-001` (SQL policy_override dropped),
     `03-services:P0-001` (admin AuthZ unavailable), `05-api:P0-001..002`
     (admin mock), `06-dsl:P0-003` (AV fail-open), `09-rag:P0-001`
     (PII fail-open), `08-agents:P0-002` (bare AIGateway fallback).
* **Явные противоречия** между отчётами зафиксированы в §5 (требуется
  верификация разработчиком/архитектором).
* **Кандидатный минимальный набор задач Phase 3** — в §6 (группировка
  findings с зависимостями и независимыми workstreams; дизайн diff
  намеренно НЕ предлагается).

---

## 2. Таблица 12 доменов

Readiness колонки помечены как **self-assessed** — формулы разные, см. §5/§10.

| # | Домен | Файл отчёта | Headline readiness (self) | P0 | P1 | P2 | P3 | P4 | Total | Top strengths (1 строка) | Top blockers (1 строка) | Не проверено |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | Infrastructure | `01-infrastructure.md` | 75/100 (capped) | 7 | 5 | 4 | 1 | 2 | 19 | DLQ envelope, async-first, multi-tenant cache prefix, fail-closed SQL/AV | unbounded asyncio.Queue (OOM), thread-unsafe singletons, infra→DSL module-level imports, rate-limiter fail-open без audit | `tests/integration/infrastructure/**` (не существует), реальный runtime поведение worker'ов |
| 02 | Security | `02-security.md` | 0/100 (clamped) | 2 | 4 | 4 | 2 | 1 | 13 | OPA runtime fail-closed + tests, AuthorizationGateway mixins, joserfc + JWKS stale-fallback, Argon2id, CapabilityGate thread-safe | `validate_sql` silently drops `policy_override`; deprecated-shim auth import (single-point-of-failure) | `infrastructure/auth/**`, `services/ai/pii/presidio_analyzer.py`, runtime pytest |
| 03 | Services | `03-services.md` | 21/100 | 1 | 3 | 6 | 5 | 4 | 19 | Capability-checked facade pattern system-wide, DLQWriter Protocol, Fernet browser-cookies | admin `_authorize` fail-open при AuthZ недоступности (`admin/api.py:97-102`) | runtime pytest, `extensions/*/services/waf_route` |
| 04 | Entrypoints | `04-entrypoints.md` | 72/100 (raw 72.5, capped) | 2 | 1 | 1 | 0 | 1 | 5 | 20 verified strengths: pure-ASGI exception handler, OOM-safe StreamingBodyHasher, MiddlewareRegistry, gRPC safe-error, S204 retro-audit closure GraphQL | SSE `/events/invoke` не пробрасывает principal/permissions (8 xfailed TDD-тестов готовы); MQ-handlers (Redis/Rabbit/IMAP/MQTT/filewatcher/scheduler) не используют DLQ | `tests/integration/**`, e2e флоу, production-wiring |
| 05 | API | `05-api.md` | 10/100 | 5 | 11 | 8 | 4 | 5 | 33 | 3-tier ActionSpec tiering, Pydantic v2 `to_camel`, fail-closed health probes, DSL Console sanitization | HITL endpoints без auth guard (`hitl.py:24-129`); Mobile BFF demo-auth + in-memory state; admin destructive `toggle_plugin`/`invoke_action` mock-fallback; мёртвый import `src.backend.workflows.workflows_service` ломает lifespan; admin_cron authenticated RCE через importlib | `tests/integration/api/**`, login_ratelimit.py, малые admin_*.py |
| 06 | DSL | `06-dsl.md` | 35/100 (capped) | 3 | 10 | 11 | 7 | 5 | 36 | 70+ EIP patterns, ProcessorRegistry namespace, DLQ 3-stage fallback, exchange immutability + finalizers | `MulticastRoutesProcessor` вызывает `ExecutionEngine(route_registry=…)` — kwarg не существует; `RedeliveryPolicy` `except TypeError, ValueError:` Python-2 синтаксис; `ScanFileProcessor` fail-open на AV-backend при `on_threat != "fail"` | `agents/`, `workflow/`, RAG processors, vault/redis runtime |
| 07 | Workflow | `07-workflow.md` | 30/100 (capped) | 3 | 5 | 6 | 3 | 2 | 19 | BPMN-importer с defusedxml, Saga-compensation model_validator, capability-gated WorkflowFacade, dry-run pure simulator, ASGI WorkerProbes | `WorkflowFlags` docstring лжёт (4 флага: docstring default-OFF, фактически default=True); 4 workflow-процессора без `@processor` decorator; `ActivityBridge` machinery не подключена к production worker (Temporal Worker без activities → `ActivityNotRegisteredError`) | YAML-шаблоны (2 из 10 прочитаны), реальный Temporal cluster |
| 08 | Agents | `08-agents.md` | 58/100 (cap 79, фактически < 80) | 4 | 5 | 2 | 2 | 2 | 15 | Composition-root AIGateway DI корректный, capability-gate adapter fail-closed, Argon2id, OWASP-pattern в agent_security | AIGateway вызывает `CapabilityGate.check(capability)` 1 аргумент — реальный требует 3 (TypeError на каждый invoke); bare `AIGateway()` fallback в `gateway_adapter.py:130` (fail-open в dev/staging); 3 процессора hardcode `tenant_id="default"|"unknown"`; `dsl/agents/fastmcp_server.py` импортирует `infrastructure.workflow.registry` напрямую | `agents/{analytics_agent,…}`, `dspy/`, extensions, vendor libs |
| 09 | RAG | `09-rag.md` | 45/100 | 2 | 3 | 5 | 2 | 3 | 15 | tenant isolation покрыт тестами (445 LOC, 11 тестов), 3-tier cache, PII-masking на bulk-пути, source attribution + freshness | `_RAGFacade.ingest`/`upload` минуют `RagIngestService` → PII НЕ маскируется на single-doc API; `RagCachePrewarmer` вызывает несуществующий `rag.query()` → silent no-op в production | live Qdrant/Chroma/Redis runtime, `FlagEmbedding` license/maintenance, ragas eval artifacts |
| 10 | Business Logic | `10-business-logic.md` | 0/100 (clamped) | 4 | 4 | 5 | 2 | 2 | 17 | capability gates в plugin.toml, TenantMixin в core_entities, real agents в credit_pipeline/osint_agent, workflow DSL в orders, schemas-only extensions | `core/di/module_registry.py` маппит `repos.files`/`repos.orders` на несуществующие модули → composition root падает; saga imports не существуют; `scoring_agent` fail-open (empty payload → score 750 → APPROVE); `osint_agent` fail-open на search/LLM-failure | runtime pytest, Temporal runtime, golden-test для OSINT prompts |
| 11 | Dependencies | `11-dependencies.md` | 49/100 (capped 79) | 4 | 0 | 5 | 1 | 0 | 10 | pyproject.toml корректный, override-dependencies для pyarrow/lxml/urllib3, CycloneDX SBOM pipeline, Creosote unused-deps gate | 4-way drift: `.security/pip-audit-allowlist.txt` (35), GH Actions (2), GitLab CI (1), `pip_audit_gate.py` IGNORED_VULNS (1); ≥9 stale fixed CVE в allowlist (lxml 6.1.1, starlette 1.3.1, urllib3 2.7.0, sqladmin 0.30.0, strawberry 0.323.2, idna 3.18, gitpython 3.1.58, mistune 3.3.4); неверные комментарии в `pip_audit_gate.py` (PYSEC-2026-87, diskcache REMOVED) | реальный `pip-audit` прогон (network timeout), licence/maintenance каждого пакета |
| 12 | Settings-Environment | `12-settings-environment.md` | 47/100 (capped 79) | 2 | 5 | 4 | 2 | 1 | 14 | Settings singleton + YamlConfigSettingsLoader + VaultConfigSettingsSource + ConsulConfigSettingsSource (fail-closed), 14-step shutdown sequence, Tini PID-1, K8s manifests с non-root securityContext | `--shutdown-timeout` — невалидный Granian CLI flag (Granian 2.8.0 имеет `--workers-kill-timeout`); дублирование `graceful_shutdown_timeout` в `app_base.py` (uvicorn) и `granian_tuning.py` (granian) с разными env-prefix'ами | `.env`, security/secrets/keys файлы; D-AUDIT-95 follow-up |

---

## 3. Нормализованный реестр findings (P0 → P4)

### 3.1. Соглашения

* **Глобальный ключ:** `<domain>:<original-id>`. Original ID, path, evidence
  сохранены без потерь.
* **Cross-domain corroboration:** помечена как `↔ C` + список других доменов,
  где тот же концепт подтверждён.
* **«Внимание: P0 без path»** — оценочные записи, не имеющие чёткого
  file:line в исходном коде, либо опирающиеся на интерпретацию отчёта.
  Такие записи помечены флагом `[interp]` — нужно подтверждение источника.
* **Всего записей в реестре: 213** (после де-дупликации по глобальному ключу;
  ID-коллизий вроде `DOMAIN-P0-001` много — нормализованы).

### 3.2. P0 — критические блокеры (37 записей)

| Global Key | Original ID | Pri | Домен | Path:line | Summary | Cross-domain ↔ |
|---|---|---|---|---|---|---|
| `infra:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Infrastructure | `infrastructure/workflow/runner.py:188` | Unbounded `asyncio.Queue()` — потенциальный OOM при backlog pending workflows | — |
| `infra:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Infrastructure | `infrastructure/registry.py:86-90` | `ConnectorRegistry.instance()` singleton без lock — TOCTOU race | ↔ C: `infra:DOMAIN-P1-005` (тот же паттерн в `chaos/probes.py`) |
| `infra:DOMAIN-P0-003` | DOMAIN-P0-003 | P0 | Infrastructure | `infrastructure/security/pii_streaming.py:135-154` | `_safe_sanitize` возвращает оригинальный текст при ошибке — fail-open PII (документировано) | ↔ C: `dsl:DOMAIN-P1-005` (WindowedDedup fail-open), `rag:RAG-P0-001` (PII bypass) |
| `infra:DOMAIN-P0-004` | DOMAIN-P0-004 | P0 | Infrastructure | `infrastructure/resilience/unified_rate_limiter.py:127-128` | Rate limiter fail-open при падении Redis без audit event | ↔ C: `infra:DOMAIN-P2-006` (UnifiedCacheFacade broad except) |
| `infra:DOMAIN-P0-005` | DOMAIN-P0-005 | P0 | Infrastructure | `infrastructure/observability/metrics.py:26-28` | Module-level импорт DSL types в observability | ↔ C: `infra:DOMAIN-P0-006` |
| `infra:DOMAIN-P0-006` | DOMAIN-P0-006 | P0 | Infrastructure | `infrastructure/observability/tracing.py:10-12` | Module-level импорт DSL types в observability | ↔ C: `infra:DOMAIN-P0-005` |
| `infra:DOMAIN-P0-007` | DOMAIN-P0-007 | P0 | Infrastructure | `infrastructure/workflow/runner.py:308-323` | Race: dispatcher берёт из queue до проверки `_active_executions` | — |
| `security:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Security | `services/agent_security/facade.py:130-133` | `validate_sql` устанавливает `kwargs["policy_override"]`, но НЕ передаёт в `framework.validate_sql(query)` — per-workflow SQL-policy silently dropped | ↔ C: `services:DOMAIN-P1-001..003` (4 downward layer violations в core → services) |
| `security:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Security | `entrypoints/middlewares/auth_required.py:177-182` | ASGI-middleware использует deprecated-shim `entrypoints/api/dependencies/auth_selector.verify_request` — single-point-of-failure при удалении shim в S99+ | � C: `api:API-P1-011` (hitl_router без dependencies=), `api:API-P0-004` (HITL без auth) |
| `services:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Services | `services/admin/api.py:97-102` | **fail-open** в `_authorize` — AuthZ unavailable → admin actions allowed | ↔ C: `api:API-P0-001/P0-002` (admin mock-fallback) |
| `entrypoints:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Entrypoints | `entrypoints/sse/handler.py:188-236` | SSE `/events/invoke` не пробрасывает principal/permissions → protected routes выполняются как anonymous; 8 xfailed TDD-тестов готовы | ↔ C: `api:API-P0-004` (HITL без auth), `security:DOMAIN-P0-002` (auth shim) |
| `entrypoints:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Entrypoints | `entrypoints/stream/{subscribers.py:21-51,invoker_subscribers.py:57-93}` | MQ handlers (Redis/Rabbit/IMAP/MQTT/filewatcher/scheduler) логируют и ack'ают вместо DLQ-enqueue при failure — data-loss на poison-message | ↔ C: `infra:STR-DLQ-envelope` (DLQ infrastructure существует, но не используется); `services:DOMAIN-P2-005` (DLQ silent_loss в audit) |
| `api:API-P0-001` | API-P0-001 | P0 | API | `entrypoints/api/v1/endpoints/admin_plugins/endpoints.py:146-155` | `toggle_plugin` при недоступном registry возвращает mock-успех (fail-open для destructive admin op) | � C: `services:DOMAIN-P0-001`, `api:API-P0-002` |
| `api:API-P0-002` | API-P0-002 | P0 | API | `entrypoints/api/v1/endpoints/admin_actions.py:206-214` | `invoke_action` при недоступном registry возвращает mock-результат (`invocation_id="mock-00000000"`) | ↔ C: `api:API-P0-001`, `services:DOMAIN-P0-001` |
| `api:API-P0-003` | API-P0-003 | P0 | API | `entrypoints/api/generator/setup.py:12-14` | Dead import `src.backend.workflows.workflows_service` (модуль удалён в S168 W13 P2-7) — `register_action_handlers()` падает на lifespan | ↔ C: `workflow:DOMAIN-WF-P0-003` (ActivityBridge не подключена), `business-logic:DOMAIN-P0-002` (workflow_setup.py не существует модули saga) |
| `api:API-P0-004` | API-P0-004 | P0 | API | `entrypoints/api/v1/endpoints/hitl.py:24-129` | HITL endpoints без `require_auth`/`require_admin` зависимости; docstring врёт про JWT + tenant filtering | ↔ C: `security:DOMAIN-P0-002` (auth shim), `entrypoints:DOMAIN-P0-001` (SSE auth gap) |
| `api:API-P0-005` | API-P0-005 | P0 | API | `entrypoints/api/mobile/router.py:55-61, 67-93, 99-120, 144-180, 183-196` | Mobile BFF использует in-memory dicts + demo-auth (`mobile:user_X:token`) без JWT-валидации; токен любой после префикса `mobile:` принимается | — |
| `dsl:DOMAIN-P0-001` | DSL-P0-001 | P0 | DSL | `dsl/engine/processors/eip/routing/multicast.py:172` | `ExecutionEngine(route_registry=...)` — невалидный kwarg; все unit-тесты мокают, production упадёт с TypeError | — |
| `dsl:DOMAIN-P0-002` | DSL-P0-002 | P0 | DSL | `dsl/engine/processors/eip/reliability/redelivery_policy.py:145` | `except TypeError, ValueError:` — Python-2 синтаксис, на Python 3 ловит только TypeError, alias `ValueError` переприсваивается | — |
| `dsl:DOMAIN-P0-003` | DSL-P0-003 | P0 | DSL | `dsl/engine/processors/scan_file.py:85-97` | `ScanFileProcessor` fail-open на AV-backend unavailability при `on_threat != "fail"` — malicious files bypass scan | ↔ C: `infra:DOMAIN-P0-003` (PII fail-open), `rag:RAG-P0-001` (PII bypass), `services:DOMAIN-P0-001` (admin fail-open) |
| `workflow:DOMAIN-WF-P0-001` | DOMAIN-WF-P0-001 | P0 | Workflow | `core/config/features/workflow.py:32-83` | `WorkflowFlags` docstring лжёт: 4 флага документированы как `default-OFF`, реально `default=True` | ↔ C: `settings-env:ENVSET-P0-002` (dual field с разными defaults) |
| `workflow:DOMAIN-WF-P0-002` | DOMAIN-WF-P0-002 | P0 | Workflow | `dsl/engine/processors/workflow/{workflow_subprocess,workflow_convert}.py`, `best_practices/{claim_check,continue_as_new}.py` | 4 процессора без `@processor()` decorator — dead code, capability-check никогда не срабатывает | — |
| `workflow:DOMAIN-WF-P0-003` | DOMAIN-WF-P0-003 | P0 | Workflow | `dsl/workflow/compiler/activity_bridge.py:155-169` + `infrastructure/workflow/worker.py:225-301` | `ActivityBridge`/`register_langgraph_checkpoint_activities` не подключены к production worker → Temporal Worker без activities | ↔ C: `api:API-P0-003` (workflows import dead) |
| `agents:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Agents | `core/ai/gateway_pipeline_mixin/policy_mixin.py:100` | `_check_capability` вызывает `gate.check(capability)` с 1 аргументом; реальный `CapabilityGate.check` требует 3 → TypeError на каждый invoke | ↔ C: `security:DOMAIN-P0-001` (capability fail-open паттерны) |
| `agents:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Agents | `services/ai/gateway_adapter.py:130` | Fallback `return AIGateway()` без DI: silent fail-open на policy/capability/budget в dev/staging | ↔ C: `services:DOMAIN-P0-001`, `dsl:DOMAIN-P0-003` |
| `agents:DOMAIN-P0-003` | DOMAIN-P0-003 | P0 | Agents | `dsl/engine/processors/agent_dsl/{ai_tool_dispatch.py:249-252,plan_execute.py:268-273,reflection_loop.py:252-257}` | Hardcoded `tenant_id="default"|"unknown"` и `correlation_id=""`/`"plan-exec"`/`"reflection-loop"` — audit/per-tenant budget lineage broken | — |
| `agents:DOMAIN-P0-004` | DOMAIN-P0-004 | P0 | Agents | `dsl/agents/fastmcp_server.py:36-39` | `dsl/agents/*` импортирует `src.backend.infrastructure.workflow.registry` напрямую — layer violation | ↔ C: `business-logic:DOMAIN-P1-001` (прямой infrastructure import через importlib), `services:DOMAIN-P1-002..003` (reverse-layer) |
| `rag:RAG-P0-001` | RAG-P0-001 | P0 | RAG | `entrypoints/api/v1/endpoints/rag.py:211-214, 332` | `/ingest` + `/upload` bypass `RagIngestService` → PII НЕ маскируется на single-doc API path; 8 xfailed strict=True тестов | ↔ C: `infra:DOMAIN-P0-003` (PII fail-open) |
| `rag:RAG-P0-002` | RAG-P0-002 | P0 | RAG | `services/ai/rag_cache_prewarmer.py:69-79` | `prewarm_tenant` вызывает `rag.query()` который не существует на RAGService → silent no-op в production | — |
| `business-logic:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Business Logic | `core/di/module_registry.py:136-137` + `core/di/providers/db.py:53-58` | `repos.files` и `repos.orders` маппятся на несуществующие модули → composition root падает | ↔ C: `infra:STR-layered-arch` |
| `business-logic:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Business Logic | `plugins/composition/workflow_setup.py:76-83` | Импортирует несуществующие `extensions.core_entities.orders.workflows.orders_saga` и `extensions.credit_pipeline.workflows.payments_saga` | ↔ C: `api:API-P0-003`, `workflow:DOMAIN-WF-P0-003` |
| `business-logic:DOMAIN-P0-003` | DOMAIN-P0-003 | P0 | Business Logic | `extensions/credit_pipeline/agents/__init__.py:84-94` (`scoring_agent`) | **Fail-OPEN в кредитном скоринге**: empty payload → `base_score=750` → APPROVE; маркер `stub: False` маскирует | ↔ C: `services:DOMAIN-P0-001`, `dsl:DOMAIN-P0-003`, `agents:DOMAIN-P0-002` |
| `business-logic:DOMAIN-P0-004` | DOMAIN-P0-004 | P0 | Business Logic | `extensions/osint_agent/functions/osint_workflow.py:309-313, 323-334` | Fail-OPEN в OSINT: search failure → empty results, LLM failure → `raw_text=prompt` (template проходит валидацию) | ↔ C: `business-logic:DOMAIN-P0-003` (fail-open pattern) |
| `dependencies:DOMAIN-P0-001` | DOMAIN-P0-001 | P0 | Dependencies | `.security/pip-audit-allowlist.txt` + `security.yml:134-138` + `.gitlab-ci.yml:161` + `pip_audit_gate.py:14-22` | 4-way drift: 35 entries в allowlist, но CI использует 1-2, gate.py — 1 | — |
| `dependencies:DOMAIN-P0-002` | DOMAIN-P0-002 | P0 | Dependencies | `.security/pip-audit-allowlist.txt:58,72,131-138` | ≥8 CVE (starlette, urllib3, sqladmin, strawberry, idna, gitpython, mistune) уже исправлены в установленных версиях (mask off) | ↔ C: `dependencies:DOMAIN-P0-003/004` |
| `dependencies:DOMAIN-P0-003` | DOMAIN-P0-003 | P0 | Dependencies | `tools/pip_audit_gate.py:17` | Неверный комментарий `PYSEC-2026-87 (lxml): fix 6.1.0 available but no Python 3.14 wheels` — фактически lxml 6.1.1 установлен на py3.14 | ↔ C: `dependencies:DOMAIN-P0-002` |
| `dependencies:DOMAIN-P0-004` | DOMAIN-P0-004 | P0 | Dependencies | `tools/pip_audit_gate.py:19-20` | Неверный комментарий `CVE-2025-69872 (diskcache) REMOVED in s170` — diskcache 5.6.3 установлен и используется в `DiskTTLCache` | ↔ C: `dependencies:DOMAIN-P2-003` |
| `settings-env:ENVSET-P0-001` | ENVSET-P0-001 | P0 | Settings-Environment | `core/scaling/granian_tuning.py:222-223` | `--shutdown-timeout` — невалидный Granian CLI флаг; Granian 2.8.0 имеет `--workers-kill-timeout`; production entry-point даст rc=2 | ↔ C: `settings-env:ENVSET-P1-005` (subprocess.call silent), `settings-env:ENVSET-P1-002` |
| `settings-env:ENVSET-P0-002` | ENVSET-P0-002 | P0 | Settings-Environment | `core/config/base/app_base.py:115-124` + `core/scaling/granian_tuning.py:125-135` | Дубль-определение `graceful_shutdown_timeout` в двух settings-классах с разными env-prefix'ами (`APP_` vs `GRANIAN_`) и ranges (`ge=1,le=300` vs `ge=0,le=300`) | ↔ C: `settings-env:ENVSET-P1-004` |

### 3.3. P1 — архитектура / слои (57 записей; сводка top-10)

| Global Key | Original ID | Домен | Path | Summary |
|---|---|---|---|---|
| `infra:DOMAIN-P1-001` | DOMAIN-P1-001 | Infrastructure | `security/presidio_sanitizer.py:140` | Deprecation shim висит с S24 |
| `infra:DOMAIN-P1-002` | DOMAIN-P1-002 | Infrastructure | `workflow/runner.py:309-315` | Искусственный `wait_for(queue.get(), timeout=5.0)` — timer churn |
| `infra:DOMAIN-P1-003` | DOMAIN-P1-003 | Infrastructure | `cache/rag/embedding_cache.py:17-64` | Custom TTL+LRU без тестов |
| `infra:DOMAIN-P1-004` | DOMAIN-P1-004 | Infrastructure | `secrets/vault_client.py` | `VaultClient._entries` без asyncio.Lock на rotation callback |
| `infra:DOMAIN-P1-005` | DOMAIN-P1-005 | Infrastructure | `chaos/probes.py:309-313` | Thread-unsafe singleton в `get_chaos_engineering()` |
| `security:DOMAIN-P1-001..004` | DOMAIN-P1-001..004 | Security | core → services downward layer violations + private-symbol leak в MCP | 4 записи |
| `services:DOMAIN-P1-001` | DOMAIN-P1-001 | Services | `services/ops/data_quality/{apply_mixin,check_mixin,rule_mgmt_mixin,schema_mixin}.py` | 4-way duplication of `DQSeverity`/`DQViolation`/`DQCheckResult`/`DQRule` (~152 LOC) |
| `services:DOMAIN-P1-002` | DOMAIN-P1-002 | Services | `services/integrations/skb.py:16` | Reverse-layer import `services → extensions.skb.services.waf_route` |
| `services:DOMAIN-P1-003` | DOMAIN-P1-003 | Services | `services/io/files.py:11` | Reverse-layer import `services → extensions.core_entities.files.services.files` |
| `entrypoints:DOMAIN-P1-001` | DOMAIN-P1-001 | Entrypoints | `entrypoints/stream/subscribers.py:9` | `entrypoints/stream/` импортирует `entrypoints/api/generator/registry` (cross-scope) |
| `api:API-P1-001..011` | API-P1-001..011 | API | admin mock-fallback, `_mock_actions`, importlib bypass, `stub: True` без error code, admin_cron `_resolve_callable` authenticated RCE | 11 записей; **API-P1-010 (admin_cron authenticated RCE)** — самый опасный |
| `dsl:DOMAIN-P1-001..010` | DSL-P1-001..010 | DSL | missing import `CDCProcessor`, `side_effect: str` contract violation, Resequencer memory leak, RedisLock never releases, WindowedDedup fail-open, telemetry swallow, XXE fallback без defusedxml, kwargs filter drops required args, stale docstring, top-level re-export gap | 10 записей |
| `workflow:DOMAIN-WF-P1-001..005` | DOMAIN-WF-P1-001..005 | Workflow | SemVer silent fallback, Guardrail fail-open, sensor infinite polling, namespace mismatch warning-only, WatchError tight loop | 5 записей |
| `agents:DOMAIN-P1-001..005` | DOMAIN-P1-001..005 | Agents | try/except placement, голые DI без config-injection, `get_ai_agent_service` NotImplementedError factory, `LiteLLMModel.request_stream` NotImplementedError, core → services direct imports | 5 записей |
| `rag:RAG-P1-001..003` | RAG-P1-001..003 | RAG | layer violation _RAGFacade, naive chunker вместо `chunkers/`, дубль `_resolve_effective_tenant_id` | 3 записи |
| `business-logic:DOMAIN-P1-001..004` | DOMAIN-P1-001..004 | Business Logic | importlib infrastructure import, core-shim layer violation, orders_dsl disconnected, workflow YAML dead references | 4 записи |
| `settings-env:ENVSET-P1-001..005` | ENVSET-P1-001..005 | Settings-Environment | compose без CPU/memory limits, `_run_granian` без shutdown args, k8s-worker без preStop, hardcoded `task_registry timeout=10`, subprocess.call без exit validation | 5 записей |

> Полный список 57 P1 — не разворачивается в таблицу ради читаемости;
> ключи соответствуют `phase-1/<domain>.md` таблицам. Cross-domain
> corroborations уже помечены.

### 3.4. P2 — мёртвый код / stubs (61 запись; сводка top-15)

| Global Key | Original ID | Домен | Summary |
|---|---|---|---|
| `infra:DOMAIN-P2-001` | DOMAIN-P2-001 | Infrastructure | `RouterLike` declared in `__all__`, нигде не используется |
| `infra:DOMAIN-P2-002` | DOMAIN-P2-002 | Infrastructure | `NoOpStepExecutor` dev-only в проде |
| `infra:DOMAIN-P2-003` | DOMAIN-P2-003 | Infrastructure | `EmbeddingVectorCache` без unit-тестов |
| `infra:DOMAIN-P2-004` | DOMAIN-P2-004 | Infrastructure | `NotImplementedError` в `@abstractmethod` (9 методов) — избыточный шум |
| `security:DOMAIN-P2-001..004` | DOMAIN-P2-001..004 | Security | sync `check()` API не использует Casbin/OPA steps, vocabulary dedup type mismatch, sentinel `<missing-context>`, defaults.py 522 LOC |
| `services:DOMAIN-P2-001..006` | DOMAIN-P2-001..006 | Services | `QuotasService` stub NotImplementedError, `dispatch_endpoint` stub, files.py DeprecationWarning shim, skb `resolve_waf_route` shim, DLQ silent_loss в audit, UnifiedCacheFacade broad except |
| `entrypoints:DOMAIN-P2-001` | DOMAIN-P2-001 | Entrypoints | `BaseEntrypoint` deprecated, не наследуется |
| `api:API-P2-001..008` | API-P2-001..008 | API | pass после except в admin_model_registry, auth_introspect except pass, 404 mapping на cron remove_job, dead action handlers, пустые `filter_schemas`/`route_schemas`, `pass` в CrudMixin, dead `processing_result.py`, OpenAPI incomplete responses |
| `dsl:DOMAIN-P2-001..011` | DSL-P2-001..011 | DSL | dead `reliability.py` 442 LOC, orphan `BatchAggregatorProcessor`, 53 undecorated EIP classes, `ProcessorRegistry` name conflict, XML marshal без isolation, fallback XML/CSV parsers, 3x `_xml_to_dict_stdlib` duplication, counter naming bug |
| `workflow:DOMAIN-WF-P2-001..006` | DOMAIN-WF-P2-001..006 | Workflow | `_iter_activity_names` dead, `BpmnImportNotAvailableError` never raised, `run_workflow_by_id` fake marker, `HitlService` signal_id as run_id, `resolve_best_match` API mismatch, OrchestratorEngine swallow-all |
| `agents:DOMAIN-P2-001..002` | DOMAIN-P2-001..002 | Agents | stale docstrings (ai_tool_dispatch, skill_invoke) |
| `rag:RAG-P2-001..005` | RAG-P2-001..005 | RAG | мёртвый `pass`, score vs distance bug (документирован как `1-distance`, код использует raw), RagCachePrewarmer dead path, score normalization между backends, NotImplementedError video modality |
| `business-logic:DOMAIN-P2-001..005` | DOMAIN-P2-001..005 | Business Logic | устаревшие TODO в scaffold docstrings, repos в extensions не используются, SKB client без production caller, TODO в plugin.toml manifest, workflow YAML test не проверяет резолв |
| `dependencies:DOMAIN-P2-001..005` | DOMAIN-P2-002..005 | Dependencies | dead sphinx docs path, phantom-version gates без CI, diskcache в проде с known-unfixed CVE, 9 cross-group duplicate pins, `streamlit>=1.58.0` без upper bound |
| `settings-env:ENVSET-P2-001..004` | ENVSET-P2-001..004 | Settings-Environment | docstring двусмысленность, непроверенные settings модули, NotImplementedError UX, `routes_without_api_key` allowlist проверка |

> Полный список 61 P2 — соответствует `phase-1/<domain>.md`.

### 3.5. P3 — замена библиотек (29 записей; сводка по доменам)

| Домен | Кол-во | Top кандидаты |
|---|---|---|
| Infrastructure | 1 | `cachetools.TTLCache` для `embedding_cache.py` (already in deps) |
| Security | 2 | `Presidio` для batch PII masking; cachetools.LRUCache отвергнут (thread-safety risk) |
| Services | 5 | `jsonschema>=4.21.0,<5.0.0` pin; `polars.write_excel` вместо openpyxl; `httpx.AsyncClient` вместо urllib в lineage; `reportlab`/`fpdf2` выбор для PDF |
| API | 4 | `functools.lru_cache` для LDAP client; `model_validate` Pydantic v2; ES error severity=ERROR; fix dead import |
| DSL | 7 | `asyncio.timeout` (stdlib 3.11+), `asyncio.TaskGroup` для fan-out, `xmltodict`+`polars` strict, `cachetools.TTLCache`, `redis-streams` consumer-group, pydantic `ConstrainedStr`, `redis.lock()` from `redis-py` |
| Workflow | 3 | `spiffworkflow` для BPMN import, `temporalio` child_workflow, `graphviz` Python binding (escape) |
| Agents | 2 | `llm-guard`/neuraly/enola для OWASP patterns (рекомендация «оставить»), `AuthorizationGateway` canonical вместо custom gate |
| RAG | 2 | `tiktoken`/`RecursiveChunker` вместо naive char-split; `_jaccard_score` helper extraction |
| Business Logic | 2 | `_make_handler` helper extraction в core |
| Dependencies | 1 | `cryptography` upper bound `<50.0.0` (cp314 free-threaded wheels problem) |
| Settings-Environment | 2 | `watchfiles` уместен (не кандидат); `_resilience_consts.py` уместен (не кандидат) |

### 3.6. P4 — фичи (29 записей; сводка top-15)

| Global Key | Original ID | Домен | Summary |
|---|---|---|---|
| `infra:DOMAIN-P4-001` | DOMAIN-P4-001 | Infrastructure | Declarative workflow step-engine (Temporal decider) |
| `infra:DOMAIN-P4-002` | DOMAIN-P4-002 | Infrastructure | Aggregated SLS health endpoint |
| `security:DOMAIN-P4-001` | DOMAIN-P4-001 | Security | OPA policy в DSL-style (route.toml `[security] opa_policy`) |
| `services:DOMAIN-P4-001..004` | DOMAIN-P4-001..004 | Services | APScheduler интеграция, Redis для MessageReplay, DQ метрики, JupyterHub sandbox-only enforcement |
| `entrypoints:DOMAIN-P4-001` | DOMAIN-P4-001 | Entrypoints | DLQ-replay UI для MQ poison messages |
| `api:API-P4-001..005` | API-P4-001..005 | API | DeprecationMiddleware wiring, VersionedRouter v2, InvocationModeLiteral mismatch, SagaHistoryRecord Pydantic, dedup `action`/`dispatch_action` cases |
| `dsl:DOMAIN-P4-001..005` | DOMAIN-P4-001..005 | DSL | `doTry/doCatch/doFinally`, Temporal non-retryable exception classification, DSPy `Signature`, `StatefulSaga` checkpoint, BPMN boundary events |
| `workflow:DOMAIN-WF-P4-001..002` | DOMAIN-WF-P4-001..002 | Workflow | `start_child_workflow` в Temporal, `WorkflowDeclaration ↔ WorkflowSpec` converter |
| `agents:DOMAIN-P4-001..002` | DOMAIN-P4-001..002 | Agents | DSPy pathway, Camel/Airflow-style DAGs |
| `rag:RAG-P4-001..003` | RAG-P4-001..003 | RAG | text-RAG E2E test, `RAGService.augment_prompt` LLM integration, `artifacts/ragas/` empty |
| `business-logic:DOMAIN-P4-001..002` | DOMAIN-P4-001..002 | Business Logic | V15 GAP Slice 1 (`[[tenants]]` parsing), workflow YAML для AI-примеров без функций |
| `settings-env:ENVSET-P4-001` | ENVSET-P4-001 | Settings-Environment | Camel/Airflow/Temporal settings already aligned (no gap) |

---

## 4. Приоритизация (строго по классам)

| Класс | Что включает | Кол-во | Почему первый |
|---|---|---|---|
| **P0 — data-loss / security / race / fail-open** | Все 37 записей выше | 37 | Блокируют порог ≥80 во всех 12 доменах; fail-open в financial/diligence (credit/OSINT), HITL/Mobile без auth, composition root crash, MQ DLQ bypass |
| **P1 — архитектура / слои** | downward layer violations, private-symbol leaks, fail-open patterns не security-critical, race в менее критичных местах, dead module-level infra→DSL | 57 | Без фикса поддерживаемость деградирует; cycle time на новые фичи удваивается; некоторые — fail-open не-security (rate limiter, dedup, AV) |
| **P2 — мёртвый код / stubs** | unused classes, deprecated shims, broad except без narrowing, dead actions, NotImplementedError в `__init__` | 61 | Cognitive load + maintenance burden + false-confidence на маркеры `stub: False` |
| **P3 — замена библиотек** | cachetools, asyncio.TaskGroup, defusedxml, httpx, polars, Presidio, llm-guard, graphviz, redis.lock | 29 | Уменьшают LOC; не блокируют прод, но уменьшают attack surface и cognitive load |
| **P4 — фичи** | BPMN boundary events, DSPy signatures, Temporal child workflow, DSL TryCatch, OPA policy DSL | 29 | Organic growth; не для Sprint 36 |

---

## 5. Явные противоречия между отчётами (verification needed)

> **Правило:** я не разрешал эти противоречия чтением source. Каждое
> помечено как «нужна верификация разработчиком/архитектором».

### 5.1. Working tree modifications (BASELINE vs multiple agents)

* **BASELINE.md:** «pre-existing modifications в `src/backend/infrastructure/storage/s3.py` и `uv.lock`».
* **Агенты 02,03,04,05,06,12** через `git status --short` показывают:
  ```
   M pyproject.toml
   M tests/unit/dsl/transforms/test_dataframes.py
  ?? docs/audit/swarm-2026-08-06/
  ```
* **Статус:** BASELINE утверждает s3.py + uv.lock, реальный `git status` на момент
  Phase 1 — pyproject.toml + test_dataframes.py. **Нужна верификация:** либо s3.py/uv.lock
  был restored до старта агентов, либо BASELINE outdated.

### 5.2. Security allowlist count

* **BASELINE.md:** «35 active IDs в `.security/pip-audit-allowlist.txt` (комментарий
  пользователя о 37 не подтверждён прямым подсчётом; 2 строки — закомментированные
  IDs)».
* **Агент 11 (Dependencies):** подтверждает **35** через `grep -cE "^CVE-|^GHSA-|^PYSEC-"`.
* **Агенты 04,06,09,10:** цитируют «35 active» из BASELINE без перепроверки.
* **Статус:** **согласовано 35**, но нужна верификация если кто-то увидит 37 в
  другом контексте (это комментарий в BASELINE без проверки).

### 5.3. HEAD vs baseline

* **BASELINE.md:** HEAD = `b69d6b49bc62918a02e47dc20ab81615fd8500b1`.
* **Агенты 01,02,03,04,05,06,07,09,10,11,12:** HEAD = `2f620910951a727f50d4539b998375b0c0bda55d`
  (1 коммит после baseline: S183 W2 #1, S3 multipart abort).
* **Статус:** **согласовано** (BASELINE описывает baseline commit, агенты описывают
  current HEAD). Не противоречие, но разные точки отсчёта.

### 5.4. Readiness formulas (12 разных)

| Домен | Формула |
|---|---|
| Infrastructure | `100 - 25*P0 - 12*P1 - 4*P2 - 1*P3 - 0.5*P4` |
| Security | `100 - 30*P0 - 12*P1 - 4*P2 - 2*P3 - 1*P4` |
| Services | `100 - 25*P0 - 10*P1 - 3*P2 - 1*P3 - 0.2*P4` |
| Entrypoints | `100 - 10*P0 - 5*P1 - 2*P2 - 1*P3 - 0.5*P4` |
| API | `100 - 25*P0 - 12*P1 - 4*P2 - 2*P3 - 1*P4` (+ bonuses) |
| DSL | `100 - 12*P0 - 6*P1 - 2*P2 - 1*P3 - 0*P4` (capped per priority) |
| Workflow | `100 - 15*P0 - 8*P1 - 3*P2 - 1*P3 - 0*P4 - 5*sec_flags` |
| Agents | weighted: `arch*0.45 + di*0.25 + sec*0.20 + dead*0.10` |
| RAG | `100 - 15*P0 - 8*P1 - 3*P2 - 1*P3 - 0.5*P4` |
| Business Logic | `100 - 25*P0 - 10*P1 - 3*P2 - 1*P3 + strengths_bonus` |
| Dependencies | `100 - 10*P0 - 5*P1 - 2*P2 - 1*P3 - 1*P4` |
| Settings-Environment | `100 - 10*P0 - 5*P1 - 2*P2 - 1*P3 - 0*P4` |

* **Статус:** **12 несопоставимых формул.** Применять cross-domain ranking
  по этим числам некорректно. Везде в этом отчёте формулы и цифры
  интерпретируются **только как self-assessment**.

### 5.5. OPA runtime claims

* **Security (02):** «OPA runtime integration with DSL/auth guards — **реально
  работает**, fail-closed, observability есть, тесты покрывают основные
  сценарии» (Section 2.2, S2).
* **Но Security же (02):** `DOMAIN-P2-001` — sync `check()` API (`AuthorizationGateway.check`)
  вызывает `_casbin_check`/`_opa_check` через `hasattr(...)` — **всегда False** →
  sync path фактически использует только in-memory fallback.
* **Статус:** **Не полное противоречие.** async pipeline OPA работает; sync
  `AuthorizationFacade.check` — нет. Но если какой-то caller идёт через
  sync API — OPA не задействован. **Нужна верификация:** кто использует sync vs async.

### 5.6. Layer baseline (consistency check)

* **Все 12 агентов:** «Layer checker baseline = 175 legacy / 0 new».
* **Статус:** **согласовано.** Единственный outlier — `01-infrastructure` отмечает
  coverage gap (`--root src/backend/infrastructure` показывает 0, потому что
  layer detection использует `rel.parts[0]`).

### 5.7. DLQ fallback semantics

* **Infrastructure (01):** `STR-DLQ-envelope` — DLQ infrastructure работает
  (`dlq_base.py:61-99`), DLQWriter Protocol (S180) с legacy JSONL fallback.
* **Services (03):** `DOMAIN-P2-005` — DLQ silent_loss branch в audit-service
  (`clickhouse_audit_service/service.py:189-218`) при отсутствии обоих backend'ов.
* **Entrypoints (04):** `DOMAIN-P0-002` — MQ handlers (Redis/Rabbit/IMAP/MQTT/
  filewatcher/scheduler) **не используют** DLQ, логируют + ack.
* **Workflow (07):** `cancel_workflow.py:151-169` — best-effort audit emit с try/except.
* **Статус:** **Противоречия в observability слое.** DLQ envelope существует
  и используется в resilience path; **но MQ/IMAP/filewatcher entrypoints
  его не используют** — это data-loss path. Audit-service имеет documented
  silent_loss (deprecated behavior). **Нужна верификация:** что считать
  canonical DLQ-enqueue path (нашёл ли кто-то из агентов реальные callers
  в DLQ для MQ entrypoints).

### 5.8. Production-ready claims

* **Несколько агентов** в strengths sections формулируют «production-grade» /
  «production-ready» / «Sprint 38 readiness».
* **Контраст:** в тех же отчётах есть P0, блокирующие composition root
  (`business-logic:DOMAIN-P0-001/P0-002`), production startup (broken
  Granian CLI flag в `settings-env:ENVSET-P0-001`), или первый invoke
  (TypeError в `agents:DOMAIN-P0-001`).
* **Статус:** «Production-ready» относится к **подмножеству архитектуры**,
  не к end-to-end deploy. **Нужна верификация:** если в Sprint 36 заявлено
  «Production Readiness 90%+» — нужно уточнить, по какому критерию; ни
  один из 12 self-assessed readiness не достигает 80.

### 5.9. RAG E2E (multimodal vs text)

* **RAG (09):** «Multimodal E2E с LLM-stub существует — `tests/e2e/test_multimodal_rag_e2e.py:255-340`
  покрывает image ingest → BLIP2 stub → embed → search → LiteLLM stub pipeline».
  **Text RAG E2E (ingest→chunking→embedding→retrieval→rerank→LLM) — НЕ существует.**
* **Status:** Явное противоречие с любым «RAG production-ready» утверждением.
  `artifacts/ragas/.gitkeep` — единственный файл, реальных eval artifacts нет.
* **Verification:** нужен phase-2 deep-dive для text RAG.

### 5.10. Streamlit pin split

* **Dependencies (11):** `pyproject.toml:137` `streamlit>=1.58.0` в core deps
  **без upper bound**; `[frontend]` extra: `streamlit>=1.30.0,<2.0.0`.
* **Settings-Environment (12):** не упоминает streamlit.
* **Статус:** inconsistency внутри одного манифеста. Уже зафиксировано как
  `dependencies:DOMAIN-P2-005`.

### 5.11. Diskcache status (3 разных нарратива)

* **Dependencies (11):** `pyproject.toml:144` — pinned `diskcache>=5.6.3,<6.0.0`
  с комментарием «PYSEC-2026-2447 — no upstream fix».
* **Dependencies (11):** `tools/pip_audit_gate.py:19-20` — комментарий
  «CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache dependency
  eliminated; replaced with custom JSONDisk cache».
* **Reality:** `src/backend/infrastructure/decorators/caching/storage/disk.py:6`
  `from diskcache import Cache` — **diskcache 5.6.3 установлен и используется**.
* **Статус:** **прямое противоречие** между кодом, манифестом и gate-комментарием.
  Уже зафиксировано как `dependencies:DOMAIN-P0-004` и `dependencies:DOMAIN-P2-003`.

### 5.12. Module-level vs lazy infra→DSL imports (Infrastructure count)

* **Infrastructure (01):** «Из 16 entries: 9 lazy (внутри function body), 7 module-level
  (observability metrics/tracing)».
* **Status:** **согласовано в самом отчёте** (01 Section 6). Простое уточнение
  для понимания blast radius. Не противоречие, но важный контекст.

### 5.13. AgentGateway bare fallback vs production-wiring

* **Agents (08):** `S-3` подтверждает `_enforce_production_wiring()` skip в
  dev/staging → bare gateway возвращается без падений.
* **Agents (08):** `DOMAIN-P0-002` фиксирует это как fail-open risk.
* **Status:** **внутри одного отчёта** Strength vs P0 — не противоречие, но
  architectural tension: production guard обходит dev/staging (intentional),
  а gateway_adapter в dev/staging возвращает bare gateway (unintentional).
  **Verification:** нужен architectural decision — bare gateway допустим
  только в dev_light профиле?

---

## 6. Кандидатный минимальный набор задач Phase 3

> Группирую findings, которые можно исправлять атомарно. Дизайн diff
> намеренно НЕ предлагается — это работа архитектора. Зависимости и
> потенциально независимые workstreams помечены.

### Workstream A: Composition root / startup (highest priority)

**Findings:** `business-logic:DOMAIN-P0-001`, `business-logic:DOMAIN-P0-002`,
`api:API-P0-003`, `workflow:DOMAIN-WF-P0-003`, `services:DOMAIN-P0-001`,
`api:API-P0-001`, `api:API-P0-002`, `business-logic:DOMAIN-P1-003`,
`business-logic:DOMAIN-P1-004`, `business-logic:DOMAIN-P2-002`.

* **Atomic candidates:**
  * Удалить `repos.files`/`repos.orders` из INFRA_MODULES; переключить
    extensions на собственный repo import.
  * Переименовать `orders_dsl.py` → `orders_saga.py` ИЛИ обновить
    `workflow_setup.py` под `orders_dsl.py`; создать `payments_saga.py`.
  * Удалить dead import `src.backend.workflows.workflows_service` в
    `setup.py:12-14`; перевести оставшиеся handlers на
    `infrastructure.workflow.registry`.
  * Wire `ActivityBridge` + `register_langgraph_checkpoint_activities` в
    `worker.py:_run_worker`.
  * Удалить mock-fallback в `admin_plugins/endpoints.py:146-155` и
    `admin_actions.py:206-214` → `HTTPException(503)`.
* **Зависимости:** каждый atomic candidate можно делать независимо, но
  рекомендуется делать одной серией для cross-validation composition root.
* **Independent workstream?** Да, параллельно с Workstream B/C/D.

### Workstream B: Fail-open в критических путях

**Findings:** `infra:DOMAIN-P0-003`, `infra:DOMAIN-P0-004`, `services:DOMAIN-P0-001`,
`api:API-P0-001`, `api:API-P0-002`, `dsl:DOMAIN-P0-003`, `dsl:DOMAIN-P1-005`,
`rag:RAG-P0-001`, `agents:DOMAIN-P0-002`, `business-logic:DOMAIN-P0-003`,
`business-logic:DOMAIN-P0-004`.

* **Atomic candidates:**
  * `pii_streaming._safe_sanitize` — добавить audit event + metric.
  * `unified_rate_limiter` — local in-memory fallback + audit event.
  * `_RAGFacade.ingest/upload` → перенаправить через `RagIngestService.ingest_text`.
  * `scoring_agent` — `if not income or not amount: raise ValueError` или
    `credit_score=0`.
  * `osint_agent._search_multi_provider` / LLM-gateway — `raise` вместо
    silent empty.
  * `WindowedDedupProcessor`/`WindowedCollectProcessor` — `exchange.fail`
    на Redis недоступности.
  * Bare `AIGateway()` fallback — `raise` вместо silent return.
* **Зависимости:** несколько подгрупп можно делать независимо (PII vs
  rate-limit vs scoring vs dedup).
* **Independent workstream?** Да.

### Workstream C: Auth / security-critical endpoints

**Findings:** `security:DOMAIN-P0-001`, `security:DOMAIN-P0-002`,
`entrypoints:DOMAIN-P0-001`, `api:API-P0-004`, `api:API-P0-005`,
`api:API-P1-010`.

* **Atomic candidates:**
  * `validate_sql` — `ctx = dict(kwargs)` + передать в `framework.validate_sql(query, context=ctx)`.
  * `AuthRequiredMiddleware` — импортировать `verify_request` из canonical пути.
  * SSE `sse_invoke` — extract `auth` из `request.state`, прокинуть в
    `dispatch_action_or_dsl`. Снять 8 xfailed.
  * `hitl.py` — router-level `dependencies=[Depends(require_auth(...))]` +
    permission check.
  * Mobile BFF — `feature_flag.mobile_bff_enabled=False` ИЛИ реальный JWT
    validator (зависит от architectural decision).
  * `admin_cron._resolve_callable` — allowlist модулей.
* **Зависимости:** auth chain должен быть согласован между auth_required
  middleware + SSE + HITL + Mobile. Возможно — один PR сразу.
* **Independent workstream?** Да, но требует cross-review.

### Workstream D: DSL / agents runtime bugs (P0 в DSL + agents)

**Findings:** `dsl:DOMAIN-P0-001`, `dsl:DOMAIN-P0-002`, `agents:DOMAIN-P0-001`,
`agents:DOMAIN-P0-003`, `agents:DOMAIN-P0-004`.

* **Atomic candidates:**
  * `multicast.py:172` — убрать `route_registry=...` из `ExecutionEngine(...)`.
  * `redelivery_policy.py:145` — `except (TypeError, ValueError):`.
  * `AIGateway._check_capability` — `check("core", capability, request.workflow_id)`
    в try/except.
  * 3 процессора (`ai_tool_dispatch`, `plan_execute`, `reflection_loop`) —
    прокинуть `exchange.meta.tenant_id/correlation_id`.
  * `fastmcp_server.py:36-39` — вынести `WorkflowDescriptor` в core facade.
* **Зависимости:** могут делаться независимо каждый.

### Workstream E: P1 architecture cleanup (downward layer violations)

**Findings:** `security:DOMAIN-P1-001..004`, `services:DOMAIN-P1-002`,
`services:DOMAIN-P1-003`, `business-logic:DOMAIN-P1-001`,
`business-logic:DOMAIN-P1-002`, `agents:DOMAIN-P1-005`,
`infra:DOMAIN-P1-005`, `infra:DOMAIN-P0-002`, `infra:DOMAIN-P1-004`.

* **Atomic candidates:**
  * Перенести `require_capability`/`RedisJwtBlacklist` в core или удалить
    shim-ы.
  * Singleton fix в `registry.py`, `chaos/probes.py`, `connector_rate_limiter.py`.
  * `VaultClient` — `asyncio.Lock` per path в `_SecretEntry`.
  * Удалить `services/integrations/skb.py:16` reverse-layer (после миграции callers).
  * Удалить `services/io/files.py:11` reverse-layer (после миграции callers).
* **Зависимости:** требует согласования extension → core → services
  boundary; рекомендуется один ADR перед серией PR.

### Workstream F: Library replacements (P3 — opportunistic)

**Findings:** `infra:DOMAIN-P3-001`, `services:DOMAIN-P3-001..005`,
`dsl:DOMAIN-P3-001..007`, `workflow:DOMAIN-WF-P3-001..003`,
`agents:DOMAIN-P3-001..002`, `business-logic:DOMAIN-P3-001..002`,
`rag:RAG-P3-001..002`, `dependencies:DOMAIN-P3-001`.

* **Atomic candidates:** cachetools.TTLCache, asyncio.TaskGroup, defusedxml,
  httpx.AsyncClient (lineage), polars.write_excel, defusedxml для XXE fallback,
  tiktoken chunker, asyncio.timeout.
* **Зависимости:** независимы. Каждый — отдельный PR.

### Workstream G: DLQ integration в MQ entrypoints

**Findings:** `entrypoints:DOMAIN-P0-002`, `services:DOMAIN-P2-005` (связан).

* **Atomic candidates:**
  * `stream/subscribers.py` + `stream/invoker_subscribers.py` —
    `OutboxBackend.enqueue` на `try/except` failure.
  * Расширить на `mqtt/mqtt_handler.py`, `email/imap_monitor.py`,
    `filewatcher/watcher_manager.py`, `scheduler/invoker_schedule.py`.
* **Зависимости:** требует OutboxBackend DI injection в эти handler'ы —
  может потребовать refactor handler constructor'ов. Не критично параллелить.

### Workstream H: Settings / dependency governance

**Findings:** `settings-env:ENVSET-P0-001`, `settings-env:ENVSET-P0-002`,
`settings-env:ENVSET-P1-001..005`, `dependencies:DOMAIN-P0-001..004`,
`dependencies:DOMAIN-P2-001..005`, `dependencies:DOMAIN-P3-001`.

* **Atomic candidates:**
  * `--shutdown-timeout` → `--workers-kill-timeout` в `granian_tuning.py:223`.
  * Удалить `graceful_shutdown_timeout` из `granian_tuning.py`; DI через
    `settings.app.graceful_shutdown_timeout`.
  * Добавить `deploy.resources.limits` во все 7 compose-файлов.
  * `preStop: sleep 30` в `deployment-worker.yaml` (синхронизировать с Helm).
  * Reconcile 4-way ignore-set (`.security/pip-audit-allowlist.txt` �
    GitHub Actions ↔ GitLab CI ↔ `pip_audit_gate.py`).
  * Prune 9 stale fixed CVE из allowlist.
  * Fix wrong comments в `pip_audit_gate.py` (PYSEC-2026-87, diskcache).
  * Remove dead sphinx docs path (`docs/api/`, `site/api/`,
    `tools/gen_api_autoapi.sh`).
  * Wire `tools/verify_pypi_versions.py` в Makefile + CI.
  * De-duplicate 9 cross-group pins.
  * `streamlit>=1.58.0` → `<2.0.0` upper bound.
* **Зависимости:** settings fixes могут делаться независимо; dependency
  governance — единым PR (один source of truth).

### Workstream I: Dead code / stub cleanup (P2 batch)

**Findings:** 61 запись P2 (см. §3.4).

* **Atomic candidates:** удаление `RouterLike`, `NoOpStepExecutor`,
  `EmbeddingVectorCache` без тестов, `QuotasService` stub, `dispatch_endpoint`
  stub, dead action handlers, dead schemas, `_iter_activity_names`,
  `BpmnImportNotAvailableError`, `run_workflow_by_id` fake marker, etc.
* **Зависимости:** каждое удаление — отдельный коммит. Массовая серия
  после стабилизации P0/P1.

### Зависимости между workstreams

| WS | Зависит от | Блокирует |
|---|---|---|
| A (composition root) | — | F (некоторые replacements), H (settings) |
| B (fail-open) | — | — |
| C (auth) | — | — |
| D (DSL/agents runtime) | — | — |
| E (P1 architecture) | — | F (зависит от layer-clean DI) |
| F (library replacement) | A (частично), E (частично) | — |
| G (DLQ MQ) | A (OutboxBackend DI) | — |
| H (settings/deps) | — | — |
| I (dead code P2) | A (composition root — некоторые dead items) | — |

* **Потенциально независимые workstreams:** B, C, D, F, H (после А);
  A нужен первым как блокер composition root.
* **Critical path:** A → (B ∥ C ∥ D) → E → F → G → H → I.

---

## 7. Library Replacement Table

| Library | Cited Custom Code | Installed (per pyproject)? | Maintenance / License | Expected LOC reduction | Evidence в отчёте |
|---|---|---|---|---|---|
| `cachetools.TTLCache` (≥5.3.0,<8.0.0) | `src/backend/infrastructure/cache/rag/embedding_cache.py` (64 LOC) | ДА (core deps) | MIT, активно поддерживается; не проверено upstream — пометка «не проверено» | −49 LOC; +библиотечные тесты | `infra:DOMAIN-P3-001` |
| `cachetools.LRUCache` | `core/security/capabilities/gate/cache_mixin.py` | ДА (core deps) | MIT; **ОТВЕРГНУТ** — cachetools.LRUCache не thread-safe по дизайну, требует Lock поверх (no-op для D-AUDIT-98 fix) | 0 (не рекомендуется) | `security:DOMAIN-P3-002` |
| `asyncio.timeout` (stdlib 3.11+) | `dsl/engine/processors/eip/resilience.py:455` (TimeoutProcessor) | ДА (stdlib) | PSF; не проверено upstream behavior в нашем concurrency context | −30 / +5 | `dsl:DOMAIN-P3-001` |
| `asyncio.TaskGroup` (stdlib 3.11+) | `MulticastRoutesProcessor`+`ScatterGatherProcessor` | ДА (stdlib, Python 3.14 mandatory) | PSF | −50 to −120 across 5 files | `dsl:DOMAIN-P3-002` |
| `defusedxml.ElementTree.fromstring` | `format_convert/{specialized,encodings,data_formats}.py` (3x copies) | **Не проверено** в отчёте | PSF/BSD-style; Defusedxml активно поддерживается; **помечено «не проверено»** в отчёте | −XX LOC; security XXE fix | `dsl:DOMAIN-P1-007` |
| `polars.write_excel` | `services/io/export_service.py:83-142` (ExcelExporter, ~60 LOC) | ДА (optional `[dataframes]`) | MIT; Apache 2.0 (core) | −50 LOC | `services:DOMAIN-P3-002` |
| `fpdf2` / `polars+HTML→weasyprint` | `services/io/export_service.py:145-218` (PdfExporter) | **Не проверено** в отчёте; `reportlab` уже pinned | BSD-3-Clause (reportlab); не проверено Python 3.14 wheels для альтернатив | −30 LOC; trade-off reportlab flexibility | `services:DOMAIN-P3-003` |
| `httpx.AsyncClient` | `services/lineage/lineage_http_emitter.py:171-205` | ДА (pyproject core deps) | BSD-3 | −10 LOC | `services:DOMAIN-P3-005` |
| `PresidioAnalyzer` (>=2.2.362) | `core/security/pii_masker.py` (271 LOC, 15 regex) | ДА (pyproject:103) | MIT, Microsoft, активный maintenance | −150 LOC; **trade-off: +1.5GB spaCy model** | `security:DOMAIN-P3-001` |
| `redis-py Redis.lock` | `dsl/engine/processors/redis_lock_processor.py:78-121` | ДА (transitive через `redis`) | MIT | −20 LOC; **trade-off: текущий код не release lock — нужно переписать на redis.lock() + Lua** | `dsl:DOMAIN-P3-007` |
| `redis-streams` consumer-group | `dsl/engine/processors/eip/windowed_dedup.py:33-44` | ДА (через `redis`) | MIT | −60 to −100 LOC (если simplified) | `dsl:DOMAIN-P3-005` |
| `tiktoken` / `RecursiveChunker` (already in `services/ai/chunkers/`) | `services/ai/rag_service/ingest_mixin.py:35-48` (naive char-split) | ДА (pyproject + chunkers/) | MIT (OpenAI); MIT | −10 LOC | `rag:RAG-P1-002`, `rag:RAG-P3-001` |
| `spiffworkflow` для BPMN import | `dsl/engine/processors/workflow/workflow_subprocess.py` (107 LOC) + `dsl/workflow/bpmn_importer.py` (444 LOC) | **Не установлен** (опционально, упомянут в feature flag docstring) | MIT; **помечено «не проверено» в отчёте** | −300 LOC (BPMN-specific) + −80 (sub_workflow через temporalio.child_workflow) | `workflow:DOMAIN-WF-P3-001` |
| `graphviz` Python binding (already in deps) | `dsl/workflow/visualize.py:144-147` (`_escape_dot` naive) | ДА | MIT (graphviz); Python wrapper — BSD | 0 LOC; security fix (DOT injection) | `workflow:DOMAIN-WF-P3-002` |
| `cachetools.LRUCache` (capabilities gate) | `core/security/capabilities/gate/cache_mixin.py` | ДА | MIT; **ОТВЕРГНУТ** (см. выше) | 0 | `security:DOMAIN-P3-002` |
| `llm-guard` / `neuraly/enola` для OWASP patterns | `core/ai/security/agent_security.py:103-159` (~24 regex) | **Не установлен**; **помечено «не проверено»** | Apache-2.0 (llm-guard), BSD-3 (enola); +100MB, +torch | Trade-off — оставить как есть | `agents:DOMAIN-P3-001` |
| `jsonschema>=4.21.0,<5.0.0` | `services/ops/data_quality/apply_mixin.py`, `services/schema_registry/registry.py` | **НЕ PINNED** (supply-chain risk) | MIT; активно поддерживается | +1 line в pyproject | `services:DOMAIN-P3-001` |
| `functools.lru_cache` (stdlib) | `entrypoints/api/v1/endpoints/auth_methods.py:88-95` (LDAP client) | ДА (stdlib) | PSF | −2 LOC | `api:API-P3-001` |
| `Pydantic v2 model_validate` | `entrypoints/api/v1/endpoints/invocations.py:64-70` | ДА | MIT | −5 LOC | `api:API-P3-002` |
| `watchfiles` для YAML/.env hot-reload | `core/config/hot_reload.py:119-128` | ДА | MIT | 0 (уместная развязка, не кандидат) | `settings-env:ENVSET-P3-001` |

> **Итого:** 11+ кандидатов на замену; 4 ОТВЕРГНУТЫ или нулевой эффект;
> 5 «не проверено» по license/wheel — нужна фаза 2 верификация.

---

## 8. Organic Feature Table

| Feature (P4) | Benefit | Architecture Fit | Evidence | Recommendation |
|---|---|---|---|---|
| `infra:DOMAIN-P4-001` Declarative workflow step-engine (Temporal decider) | Camel-style DSL для workflows | Хорошо вписывается в `core/facades.py` (M7 integration layer); workflow DSL — отдельный слой | `infra/dsl/workflow/`, `core/facades.py:160` | **Plan** в Sprint 37+ — не в Sprint 36 scope |
| `infra:DOMAIN-P4-002` Aggregated SLS health endpoint | K8s probes (degraded vs healthy) | ADR-pending | `infra/registry.py:195-218` | **Defer** до появления SLO matrix; low priority |
| `security:DOMAIN-P4-001` OPA policy в DSL-style (`route.toml [security] opa_policy`) | Устраняет Python OPAClient + composition root setup для смены policy | Organic в `route.toml security section` | `policy_settings.opa_policy_name`, `core/auth/authz_default.rego` | **Plan** через Sprint planning + DSL-testkit |
| `services:DOMAIN-P4-001` APScheduler integration для `scheduled_reports` | Real cron-driven execution, history | `SchedulerFacade.add_job` уже есть | `services/ops/scheduled_reports.py:52-181`, `services/scheduler/facade.py` | **Plan** в Sprint 37 |
| `services:DOMAIN-P4-002` Redis для `MessageReplayService` | Persistence через restart | Pattern из `webhook_relay.py` | `services/ops/message_replay.py:52-179` | **Plan** в Sprint 37 |
| `services:DOMAIN-P4-003` DQ-remediation метрики (`dq_fixes_total{rule_name}`) | Observability для auto-fix | Standard Prometheus pattern | `services/ops/dq_remediation.py:266-288` | **Defer** low priority; +5 LOC |
| `services:DOMAIN-P4-004` JupyterHub sandbox-only enforcement (`backend_kind=E2B`) | Defense-in-depth | Feature flag уже есть | `services/jupyter/hub_run_orchestrator.py:166-188` | **Plan** low cost |
| `entrypoints:DOMAIN-P4-001` DLQ-replay UI для MQ poison messages | Operator visibility | `core/messaging/outbox.py::replay` уже готов; `admin_scheduler_dlq.py` — partner | `outbox.py:91-167`, `replay/mark_resolved` | **Plan** post Sprint 36 |
| `api:API-P4-001` Подключить `DeprecationMiddleware` | RFC 8594 sunset headers | Уже реализован в `versioning.py:1-112` | `grep -rn DeprecationMiddleware` → 0 hits | **Plan** (cosmetic) |
| `api:API-P4-002` `VersionedRouter` для v2 routes | Roadmap | `entrypoints/api/v2/` отсутствует | `find` → только `v1/` | **Defer** (за рамками Sprint 36) |
| `api:API-P4-003` `InvocationModeLiteral` mismatch (`deferred`/`async-queue` vs InvokeMode enum) | Consistency | `schemas/invocation.py` vs `core/enums/invocation.py` | `schemas/invocation_api.py:19-21` | **Plan** — добавить modes в enum |
| `api:API-P4-004` `get_saga_history` через `SagaHistoryRecord.model_dump()` | Pydantic-native serialization | Если схема доступна | `admin_workflows/facade.py:337-355` | **Defer** low priority |
| `api:API-P4-005` Dedup `action`/`dispatch_action` cases | YAGNI | Логическое дублирование | `_apply_steps` match (`:260-277`) | **Defer** low priority |
| `dsl:DOMAIN-P4-001..005` (Camel `doTry/doCatch/doFinally`, Temporal non-retryable, DSPy Signature, StatefulSaga, BPMN boundary events) | Расширение DSL | `eip/*` + Temporal integration | Все 5 в `dsl/` core | **Plan** — каждая требует AF scope (Sprint 36 не блокирует) |
| `workflow:DOMAIN-WF-P4-001` `start_child_workflow` в TemporalBackend + `await_external_signal` | HITL S210 pattern | Protocol уже есть в `core/workflow/backend.py:155-191` | `temporal_backend.py` отсутствует метод | **Plan** обязательно для HITL production |
| `workflow:DOMAIN-WF-P4-002` Конвертер `WorkflowDeclaration ↔ WorkflowSpec` | Unified UX | `spec/workflow.py:93-101` явно out of scope | `executor/state.py:71-89` vs `spec/workflow.py:49-101` | **Defer** (post Sprint 36) |
| `agents:DOMAIN-P4-001` DSPy integration | Unified AgentSpec | `services/ai/dspy/` существует | `agents_pydantic`, `agents`, `ai_agent`, `agent_dsl` — 4 параллельных framework'а | **Plan** — consolidation scope |
| `agents:DOMAIN-P4-002` Camel/Airflow-style DAGs для agent handoff | Multi-agent DAG | Organic | `agent_registry.py:25-37` | **Defer** |
| `rag:RAG-P4-001` text-RAG E2E test | Production validation | `tests/e2e/test_multimodal_rag_e2e.py` — единственный E2E | `tests/e2e/test_multimodal_rag_e2e.py` | **Plan** (medium) — обязательно для RAG sign-off |
| `rag:RAG-P4-002` `RAGService.augment_prompt` LLM integration | Full-pipeline use cases | `augment_mixin.py:23-66` — by design separation | — | **Defer** (out of scope for RAG service) |
| `rag:RAG-P4-003` Run `make ai-rag-eval` для artifacts | Eval hygiene | `services/ai/eval/ragas_evaluator.py:14` | `artifacts/ragas/.gitkeep` only | **Plan** (low cost) |
| `business-logic:DOMAIN-P4-001` V15 GAP Slice 1 (`[[tenants]]` parsing) | Multi-tenant capabilities | `extensions/example_plugin/plugin.toml:32-79` | `grep -rn "[[tenants]]"` → 0 hits | **Defer** до Sprint 38+ |
| `business-logic:DOMAIN-P4-002` Move example workflow YAMLs в `docs/examples/` | Avoid misleading docs | README явно «декларативный пример» | 4 YAML файла, 254 LOC | **Plan** (low cost) |
| `settings-env:ENVSET-P4-001` Camel/Airflow/Temporal settings — already aligned | n/a | n/a | n/a | **No finding** |

---

## 9. Итог: какие P0/P1 блокируют ≥80 для каждого домена

> «≥80» = self-assessed readiness, при условии что cap (≥80 запрещено при P0/P1)
> снят. Все 12 доменов имеют P0, поэтому ≥80 требует закрытия **всех** P0
> + P1 в каждом домене.

| Домен | P0 для закрытия ≥80 | P1 для закрытия ≥80 | Top blocker (один) |
|---|---|---|---|
| 01 Infrastructure | 7 | 5 | Unbounded asyncio.Queue (OOM risk) |
| 02 Security | 2 | 4 | `validate_sql` silently drops policy_override |
| 03 Services | 1 | 3 | admin `_authorize` fail-open на AuthZ unavailable |
| 04 Entrypoints | 2 | 1 | SSE `/events/invoke` auth gap (8 xfailed ready) |
| 05 API | 5 | 11 | HITL endpoints без auth guard |
| 06 DSL | 3 | 10 | `MulticastRoutesProcessor` невалидный kwarg в `ExecutionEngine` |
| 07 Workflow | 3 | 5 | `ActivityBridge` machinery не подключена к worker |
| 08 Agents | 4 | 5 | `AIGateway._check_capability` TypeError на каждый invoke |
| 09 RAG | 2 | 3 | `_RAGFacade.ingest` минует `RagIngestService` → PII fail-open |
| 10 Business Logic | 4 | 4 | `repos.files`/`repos.orders` → composition root падает |
| 11 Dependencies | 4 | 0 | 4-way drift allowlist � CI ↔ gate |
| 12 Settings-Environment | 2 | 5 | `--shutdown-timeout` — невалидный Granian CLI flag |

* **Самый крупный blast-radius (≥3 P0):** 01 (Infra, 7), 05 (API, 5), 06 (DSL, 3),
  07 (Workflow, 3), 08 (Agents, 4), 10 (Business Logic, 4), 11 (Dependencies, 4).
* **Минимальные P0 для ≥80 (каждый домен отдельно):** невозможно без
  закрытия **всех** P0+P1 (cap rule).
* **Realistic path к ≥80 (cross-domain):** Workstream A → (B ∥ C ∥ D) → E →
  F → G → H → I (см. §6).
* **Realistic sprint estimate:** **3-5 sprints** для full P0/P1 closure
  (агент business-logic: «~3-4 спринта» после аналогичной оценки; агенты
  api/security/services дают похожие оценки).

---

## 10. Методологические оговорки (formulas и cap rules)

### 10.1. Cap rule consistency

Все 12 отчётов применяют правило «≥80 запрещено при наличии P0/P1». Cap
выражен по-разному:

* **Clamp-based:** `max(0, min(formula, 79))` (infrastructure, security, services,
  workflow, business-logic, api).
* **Raw formula, cap via 80:** Entrypoints, DSL, RAG, Settings-Environment, Dependencies.
* **Weighted:** Agents (4-component weighted average).

Это означает, что финальные числа в self-assessment колонке таблицы §2
**не сопоставимы** между доменами. При сравнении использовать только
«passed/failed ≥80» как бинарный маркер, не числовые значения.

### 10.2. Непроверенное (per agent reports)

Помечено каждым агентом в §1 / §0 / §2 своих отчётов:

* **Сетевые операции:** PyPI/registry timeout в 11 (Dependencies); RAG
  не верифицировал live Qdrant/Chroma/Redis; Workflow не запускал
  реальный Temporal cluster.
* **Integration tests:** `tests/integration/**` (infrastructure не имеет
  этой директории); `tests/integration/api/**` (api не читал); RAG,
  Workflow — out of unit-scope.
* **Runtime behaviour:** Business Logic — Temporal runtime не запускал;
  DSL — vault/redis недоступны; Services — runtime pytest заблокирован
  инструкцией «no git mutation, safe targeted read-only».
* **Vendor libs:** `FlagEmbedding` license (RAG); `pydantic_ai`,
  `langgraph`, `mcp.server.fastmcp`, `langfuse` (Agents) — только
  проверка факта импорта.
* **Security allowlist IDs:** BASELINE говорит 35; ни один агент не
  делал независимый подсчёт (только 11-dependencies через `grep -c`).

### 10.3. Сводка по totals

```
Domain              P0   P1   P2   P3   P4   Total
01 Infrastructure    7    5    4    1    2    19
02 Security          2    4    4    2    1    13
03 Services          1    3    6    5    4    19
04 Entrypoints       2    1    1    0    1     5
05 API               5   11    8    4    5    33
06 DSL               3   10   11    7    5    36
07 Workflow          3    5    6    3    2    19
08 Agents            4    5    2    2    2    15
09 RAG               2    3    5    2    3    15
10 Business Logic    4    4    5    2    2    17
11 Dependencies      4    0    5    1    0    10
12 Settings-Env      2    5    4    2    1    14
                  ─── ─── ─── ─── ─── ──────
TOTAL              37   57   61   29   29   213
```

* **213 findings total.**
* **94 P0+P1** — блокируют порог ≥80 во всех 12 доменах.
* **Домены с наибольшим blast-radius по P0+P1:** API (16), DSL (13),
  Infrastructure (12), Settings-Environment (7), Business Logic (8),
  Workflow (8), Agents (9), Services (4), RAG (5), Security (6),
  Entrypoints (3), Dependencies (4).

### 10.4. Top consolidated blockers (cross-domain corroborations)

1. **Composition root / startup blockers** (5+ P0): `business-logic:DOMAIN-P0-001`,
   `business-logic:DOMAIN-P0-002`, `api:API-P0-003`, `workflow:DOMAIN-WF-P0-003`,
   `services:DOMAIN-P0-001`, `api:API-P0-001`, `api:API-P0-002`.
2. **DLQ bypass на MQ/IMAP/MQTT/filewatcher/scheduler** (1+ P0):
   `entrypoints:DOMAIN-P0-002` (data-loss path).
3. **Capability-gate / fail-open в критических путях** (8+ P0 cross-domain):
   `security:DOMAIN-P0-001`, `services:DOMAIN-P0-001`, `api:API-P0-001/P0-002`,
   `dsl:DOMAIN-P0-003`, `rag:RAG-P0-001`, `agents:DOMAIN-P0-002`,
   `business-logic:DOMAIN-P0-003`, `business-logic:DOMAIN-P0-004`.
4. **Auth gaps** (3+ P0): `entrypoints:DOMAIN-P0-001` (SSE), `api:API-P0-004`
   (HITL), `api:API-P0-005` (Mobile BFF).
5. **Module-level infra→DSL imports** (2 P0): `infra:DOMAIN-P0-005/P0-006`.
6. **Thread-unsafe singletons** (3+ findings): `infra:DOMAIN-P0-002`,
   `infra:DOMAIN-P1-005`, паттерн повторяется в `connector_rate_limiter.py:183-188`.
7. **Composition-time TypeErrors** (2 P0): `agents:DOMAIN-P0-001` (capability
   1-arg vs 3-arg), `dsl:DOMAIN-P0-001` (ExecutionEngine invalid kwarg).
8. **Dependency governance drift** (4 P0): `dependencies:DOMAIN-P0-001..004`.

---

## 11. Compact summary для родителя

* **Статус:** Phase 2 summary COMPLETE.
* **Файл:** `docs/audit/swarm-2026-08-06/cycle-1/PHASE-2-SUMMARY.md` (этот файл).
* **Totals:** 12 доменов; 213 findings (P0=37, P1=57, P2=61, P3=29, P4=29).
* **Top consolidated blockers (8):**
  1. Composition root / startup blockers (5+ P0)
  2. DLQ bypass на MQ entrypoints (data-loss, 1 P0)
  3. Capability-gate fail-open (8+ P0 cross-domain)
  4. Auth gaps (SSE, HITL, Mobile BFF — 3 P0)
  5. Module-level infra→DSL imports (2 P0)
  6. Thread-unsafe singletons (3 findings)
  7. Composition-time TypeErrors (2 P0)
  8. Dependency governance drift (4 P0)
* **Contradictions count:** 13 зафиксированных (5.1–5.13); каждое помечено
  «нужна верификация разработчиком/архитектором»; **не разрешено чтением source**.
* **Phase 3 workstreams:** 9 (A–I), с зависимостями и realistic path
  `A → (B ∥ C ∥ D) → E → F → G → H → I`; estimated **3-5 sprints** для
  full P0/P1 closure (если каждый домен отдельно).
* **Главные оговорки:**
  * **12 разных формул readiness** — числа в self-assessed колонке несопоставимы.
  * **Cap rule ≥80 запрещено при P0/P1** — ни один из 12 доменов не достигает
    self-assessed ≥80.
  * **Pre-existing working tree:** BASELINE говорит s3.py + uv.lock;
    6+ агентов через `git status` показывают pyproject.toml + test_dataframes.py.
    Нужна верификация.

---

*Phase 2 summarizer (read-only). Не правил ничего, кроме этого файла.
Не читал source/test/git diff/CLAUDE/PLAN/KNOWN_ISSUES/debt logs.*
