# CONTEXT.md

## Текущее состояние (2026-05-21 14:00, после Sprint 16 Waves 3-7 GAP closure)

**HEAD**: `ecaa198e [wave:s16/w7-clamav-production-wire]` — B-3 finale full closure (interface + production wire).
**Активный спринт**: **Sprint 16 «Closure»** — Waves 0/3/4/5/6/7 CLOSED; параллельная активность кросс-сессий не блокирует.
**План**: `PLAN.md` V22 FINAL (5 спринтов × 2 недели × 5 команд).
**GAP-анализ executive план**: gap-analysis/GAP-report 2026-05-21 (внешний senior architect аудит).

### Sprint 16 — Wave-таблица текущей сессии

| Wave | Commit | Закрыто |
|---|---|---|
| `w3-config-validator` | `06142dda` | **B-2** WAF strict-in-prod + **B-9** ConfigValidator startup gate |
| `w4-task-registry-coverage` | `f0b0a7b9` | **B-8** TaskRegistry 22/24 callsites (2 secrets carryover) |
| `w5-mw-dedup-scheduler-metrics` | `cd5dcbf3` | **M-1** APIKey/AuthRequired dedup + **M-9/CP-22** APScheduler observability |
| `fix-clamav-tcp-syntax` | `b101de85` | Critical Python 2 SyntaxError в `clamav_tcp.py:43` |
| `w6-async-payload-scanner` | `4c9f6eaa` | **B-3 finale interface**: AsyncPayloadScanner + WafPolicy.evaluate_async + ClamAVPayloadScanner |
| `w7-clamav-production-wire` | `ecaa198e` | **B-3 finale production wire**: feature-flag + wire + ConfigValidator rule |

### Готовность по слоям (актуальная)

| Слой | Оценка | Статус | Закрыто за сессию |
|---|---|---|---|
| L1 Gateway/Middleware | 8/10 | 🟢 | M-1 dedup |
| L2 Auth | 7/10 | 🟡 | M-2 был уже закрыт ранее |
| **L3 WAF/Outbound** | **9/10** | 🟢 | B-2 + B-3 finale (+2.5) |
| L4 DSL/Routes | 8/10 | 🟢 | — |
| L5 AI/RPA/Plugins | 8.5/10 | 🟢 | — |
| L6 Entrypoints | 9/10 | 🟢 | — |
| L7 Observability | 9/10 | 🟢 | CP-21 + M-9/CP-22 |
| L8 Tests | 8/10 | 🟡 | — (coverage 50%→70% carryover) |
| L9 CI/CD | 7.5/10 | 🟡 | — (push pending) |
| L10 Security | 9/10 | 🟢 | B-2 + B-9 + B-3 + ClamAV imports |

**Среднее**: **8.30/10** (было 7.7).

> **Timing-note (важно для интерпретации)**: текущая оценка **8.30/10 (post S16 Waves 3-7)** отражает закрытые B-2 (WAF strict-in-prod) / B-3 (ClamAV PayloadScanner) / B-9 (ConfigValidator). Baseline **GAP-аудит pre-S16 = 5.7/10** (10 слоёв × 4 вектора, см. `.claude/KNOWN_ISSUES.md` секцию «GAP-аудит 2026-05-21»). Цифры не противоречат: разница 5.7 → 8.30 — это эффект S16 Waves 3-7 closure. При onboarding нового разработчика читать обе оценки в указанном порядке (GAP-аудит как baseline → текущая таблица как delta).

### Закрытые P0 блокеры

✅ **B-2** WAF strict-in-prod (Wave 3)
✅ **B-3** ClamAV PayloadScanner — interface (Wave 6) + wire (Wave 7)
✅ **B-8** TaskRegistry coverage (Wave 4; 2 secrets carryover)
✅ **B-9** ConfigValidator (Wave 3)

### Открытые P0 блокеры (для следующих сессий)

- **B-1** SAML completion (`parse_idp_metadata` + SP endpoints) → Sprint 18 К1
- **B-4** OWASP ZAP fail-on-medium → Sprint 18 К1
- **B-5** EntryGateway для 14 protocol adapters → Sprint 17 EG-1 contract-test
- **B-6** FeatureFlagService finale (Redis pub/sub + admin endpoint) → CP-15 Sprint 17 К1
- **B-7** AuditService.emit unified → CP-20 Sprint 17 К3

### Открытые риски

1. **B-8 carryover**: 2 callsites `asyncio.create_task` в `infrastructure/secrets/` под path-policy.
2. **6 baseline failures** в `tests/unit/core/net/test_outbound_http.py` — env SOCKS proxy, не из изменений.
3. **lint-strict 164 errors** carryover (S112/BLE001).
4. **OTel Wave 1 unit-тесты** pre-merge gate carryover.
5. **`M src/backend/core/plugin_runtime/sandbox.py`** — pre-merge gate ожидает S18/S19 strategy.
6. **Push pending 100+ commits** — commit-policy запрещает без явного запроса.

### Выполненные команды проверки за сессию

- 67 unit-тестов добавлены, все PASS (22 ConfigValidator + 5 scheduler-obs + 2 api_key-dedup + 9 waf-async + 3 outbound-async + 8 payload-scanner + 4 waf-setup-clamav).
- ruff + mypy на ВСЕХ новых файлах clean (baseline issues подтверждены через `git stash` сравнение).
- Smoke import validator/lifecycle/observability/clamav backends — OK.

### Следующий шаг

**Sprint 17 «Centralization» (наиболее логичный кандидат)**:

1. **CP-15 FeatureFlagService finale** (B-6, 2-3 дня) — Redis pub/sub + admin endpoint + audit hook. Зависит от CP-20.
2. **CP-20 AuditService.emit() unified** (B-7, 3-5 дней) — единый emit, рефакторинг 4 callsites, ClickHouse outbox.
3. **CP-17 AuthorizationGateway** (M-5, 3-5 дней) — фасад над Casbin/OPA/CapabilityGate/AdminRoles.
4. **CP-18 MetricsRegistry** (M-8, 4-6 дней) — idempotent registry, миграция 30 Counter + 6 Histogram.

**Альтернатива** — Sprint 18 «Security Final»: B-1 SAML + B-4 ZAP + B-5 EntryGateway contract-test.

**Перед любым следующим wave** обязательно: `make ci` + `docker compose -f ops/compose/docker-compose.yml config` (M-10 carryover smoke verify).

### Архив + сессии

- `vault/session-2026-05-21-1400-summary.md` — детальная сводка этой сессии (Waves 3-7).
- `vault/session-2026-05-2[01]-*-summary.md` — предыдущие сессии.
- `vault/archive-plan-v21.md` — архив PLAN.md V21.
- `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` — внутренний V3.0 (38 GAP по 14 доменам).

---

## GAP-аудит 2026-05-21 — onboarding для нового разработчика

> Эта секция — карта-маршрут для новичка, который заходит на pre-production gd_integration_tools после 15+ закрытых спринтов и активного Sprint 16. Полные findings — `.claude/KNOWN_ISSUES.md` (секция GAP-аудит 2026-05-21).

### 1. Сначала прочитать (≤ 30 минут)

1. **`PLAN.md` секции 0–2** (видение, принципы V22, команды) — что строим и почему.
2. **`ARCHITECTURE.md` секция «Архитектурная схема» + «Слои L1–L10»** — как устроено.
3. **`.claude/KNOWN_ISSUES.md` секция «GAP-аудит 2026-05-21»** — что сломано/неготово прямо сейчас.
4. **`.claude/DECISIONS.md` ADR-NEW-1..4** — 4 архитектурных решения для Sprint 17 (что меняем).

### 2. Готовность слоёв (10-слойный аудит, среднее **5.7/10**)

| Слой | Оценка | Главная боль |
|------|--------|--------------|
| **L8 Security** | **7.0** ✅ | OWASP ZAP non-blocking; OPA не интегрирован runtime |
| **L2 Core Kernel** | **6.5** | ActionMetadata без retry-policy; lifecycle не идемпотентна; `providers.py` Any-returns (S-L2-1 Exchange.stopped REVISED — property-based, не баг) |
| **L3 Routes** | **6.5** | Routes не проходят capability-gate; tenant-aware сломан |
| **L4 AI Pipelines** | **6.5** | Banking processors (KYC/AML/CreditScoring) — empty shells |
| **L1 Gateway/MW** | **6.0** | Plugin-registry отсутствует; per-route override невозможен |
| **L10 Test Coverage** | **5.9** | testkit/ public API отсутствует; PBT/mutation = 0%; E2E = 1 файл |
| **L5 RPA** | **5.0** | Browser context leak; нет WAF для browser; нет session persistence |
| **L7 Observability** | **5.0** | OTel trace_id не в structlog; Graylog FD leak; CH audit без retry |
| **L9 DevOps** | **5.0** | K8s manifests неполные; pre-prod-check v2 не реализован; DR отсутствует |
| **L6 Data&State** | **3.0** ⚠️ | 70+ Python 2 syntax-errors (grep `-l` = 71) → импорт невозможен |

### 3. 🔴 P0 блокеры pre-production (17 — все в Sprint 17)

**Прежде чем писать новую фичу**, знай о:

1. **70+ файлов с Python 2-style `except E1, E2:`** (точный grep `-l` = 71) — приходят из L6 (database/clients/storage/logging/secrets), L7 (`tracing.py`, `mcp_server.py`, `workspace_manager.py`), L5 (`rpa.py:816`), а также `dsl/`, `services/`, `entrypoints/`. CI-импорт падает. Сводный fix через codemods — `[wave:s17/k1-w0-python3-except-clause-sweep]` (см. F-A-4 codemod pre-test gate в DoD).
2. **FTP/IMAP TLS CERT_NONE** в трёх файлах (V1 violation, банковский compliance) — `[wave:s17/k1-w1-tls-cert-required]`.
3. **AuthorizationGateway отсутствует** (ADR-NEW-1) — единая точка авторизации (Casbin/OPA/CapabilityGate) — `[wave:s17/k1-w2-authorization-gateway]`.
4. **CapabilityGateway Protocol** не вынесен в `core/interfaces/` (ADR-NEW-4) — Clean Architecture violation.
5. **Routes без capability-gate** — `services/routes/loader.py:70` пропускает declare(); security violation.
6. **Tenant-aware routes сломаны** — `RouteManifestV11.tenant_aware` читается, но не пробрасывается в DSL-шаги.
7. **`call_function_modules` dev fallback** = пустой whitelist пропускает все модули → RCE в production.
8. **Saga state store отсутствует** — workflow-гарантии не полны.
9. **K8s manifests неполные** — есть только HPA для temporal-worker, нет Deployment/Service/PDB/Ingress.
10. **`make pre-prod-check v2 (38/38)` не реализован** — V22 final DoD заблокирован.
11. **БД migrations не в deploy-flow** — нет init-container.
12. **Backup/DR procedures отсутствуют** — нет `ops/backup/`, нет runbook'ов.

### 4. ✅ Сильные стороны (можно копировать в новые модули)

- **CapabilityGate** (`core/plugin_runtime/capability_gate.py`) — LRU-кэш + subset-проверка + audit-callback. **Цитировать в подобных gateway/policy-engines.**
- **OutboundHttpClient + WafPolicy** (`core/net/outbound_http.py`) — обязательный fascade для всех `:external` HTTP. **Расширять для новых протоколов (SOAP/gRPC/MQ).**
- **Camel-style Exchange/Pipeline** (`dsl/engine/exchange.py` + `pipeline.py`) — каноничный аналог Apache Camel. **Использовать как образец для новых processor-цепочек.**
- **AuthRequiredMiddleware** (`entrypoints/middlewares/auth_required.py`) — централизованная auth (6 методов). **Маршруты auth-агностичны — не добавлять `Depends(get_user)` в endpoint.**
- **structlog batching** (`infrastructure/observability/structlog_batching.py`) — feature-flagged batching wrapper. **Использовать для high-RPS логирования.**
- **TaskRegistry** (`core/utils/task_registry.py`) — все `asyncio.create_task` через registry с lifecycle (V22 obligatory).

### 5. Антипаттерны (не делать никогда)

- ❌ `except ConnectionError, OSError:` — Python 2 syntax (CI gate failed). Используй `except (ConnectionError, OSError):`.
- ❌ `ssl.CERT_NONE` / `check_hostname=False` — V1 violation (банковский compliance).
- ❌ Прямой `requests.get(...)` или `httpx.get(...)` для `:external` URL — обязательно через `OutboundHttpClient`.
- ❌ `asyncio.create_task(...)` напрямую — через `TaskRegistry.create_task(name, deadline)`.
- ❌ `= Counter(...)` / `= Histogram(...)` напрямую (S17 V22) — через `MetricsRegistry.get_counter(name, labels)`.
- ❌ `if request.user.is_admin` ad-hoc auth — через `AuthorizationGateway.authorize(...)` (S17).
- ❌ `from gd_integration_tools.infrastructure.*` в `services/` или `core/` — Clean Architecture violation (`make layers` поймает).
- ❌ AI-плагин пишет в существующий файл — capability `fs.write.*` запрещена; только `fs.create_new.<workspace>`.

### 6. Если работаешь над…

- **Auth/Security** → начни с `core/security/` + `core/auth/` + read `tools/check_waf_coverage.py`. Делай через `AuthorizationGateway` (S17).
- **DSL/Routes** → `dsl/route/builder/` (миксины) + `routes/echo_demo/` (пример). Не забудь capability-gate в loader.
- **Plugin** → `extensions/example_plugin/plugin.toml` (шаблон) + V11 manifest + capability declaration ДО import.
- **Workflow** → `dsl/workflow/` + Temporal SDK; `LiteTemporalBackend` для dev_light. Saga state model — пока отсутствует (S17).
- **AI/RAG** → `services/ai/` + `core/ai/workspace_manager.py` (workspace isolation обязательна) + `infrastructure/cache/rag/` (3-tier).
- **Observability** → `infrastructure/observability/otel_auto.py` (9 instrumentators) + structlog batching. Не забудь правильный shutdown order.
- **Database** → advanced-alchemy + asyncpg async-only; connection pool обязательно с `pool_pre_ping=True`; outbox pattern для messaging.

### 7. Sprint 17–S20 (GAP-driven replace V22, см. PLAN.md)

- **S17 Centralization Hardening** — 17 P0 блокеров + ADR-NEW-1..4 backbone
- **S18 Operational + Security carryover** — S-L1/S-L7/S-L8 пробелы + K8s Helm + БД migration init-container + multi-tenant rate-limit + WAF allowlist tightening
- **S19 DSL+AI расширения + DX** — workflow versioning + route composition + route authz + multipart RAG + reranking + RPA sessions + VSCode extension + Adaptive RAG strategy
- **S20 Production Signoff** — pre-prod-check v2 38/38 + coverage 83% + mypy 0 + p95 ≤80ms + RPS ≥1500 + DR & Backup verified + canary 1→10→50→100%

### 8. Команды для быстрой ориентации

```bash
make help                  # все команды Makefile с группами
manage.py --help           # CLI 52K со скаффолдингом + диагностикой
make ci                    # lint + type + test + coverage + security
make pre-prod-check        # текущие 20/38 gates (v2 — Sprint 20)
make routes                # каталог зарегистрированных routes
make actions               # каталог зарегистрированных actions
make plugin-schema         # JSON-Schema валидация plugin.toml
make check-waf-coverage    # все :external через OutboundHttpClient
make layers                # check_layers.py --strict-extensions
```

---
