# Итоговый отчёт: аудит `gd_integration_tools`

> Дата: 2026-06-09
> Метод: 5 итераций × 5-6 параллельных агентов + web search
> Масштаб: 1653 Python-файлов, ~76k statements, 12+ протоколов, 7 extensions

---

## 1. Сводная таблица оценок

| Итерация | Тема | Оценка | Вес | Взвешенный |
|----------|------|--------|-----|------------|
| 1 | Инфраструктура, Docker, resilience, perf, observability | **6.4/10** | 20% | 1.28 |
| 2 | БД, сервисы, extensions, DSL, логирование, отказоустойчивость | **6.3/10** | 20% | 1.26 |
| 3 | Фронтенд, API, multi-protocol, OpenAPI, security | **6.4/10** | 20% | 1.28 |
| 4 | DSL роуты, workflow, AI, RPA, интеграция слоёв | **6.3/10** | 20% | 1.26 |
| 5 | Документация, CI/CD, мёртвый код, зависимости, тесты | **6.5/10** | 20% | 1.30 |
| **ИТОГО** | | **6.38/10** | 100% | **6.38** |

**Доверительный интервал:** 6.0–6.8 (учитывая subjectivity оценок и частичную выборку).

---

## 2. Детализация по итерациям

### Итерация 1: Инфраструктура (6.4/10)

| Компонент | Балл | Ключевой факт |
|-----------|------|---------------|
| Docker / K8s | 7/10 | Дрифт UID (10001 vs 1000), worker без проб, raw K8s дублирует Helm |
| DSL ↔ Инфра | 5/10 | `InfrastructureDSL` — 11 мёртвых stub'ов. Sink'и per-call — нет pooling |
| Resilience | 8/10 | 11 fallback-цепочек, chaos tests, SelfHealer. Нет per-tenant bulkhead |
| Performance | 6/10 | `pool_use_lifo` не прокинут. Blocking I/O в `imports.py`. HPA worker дрифт ×100 |
| Observability | 6/10 | K8s probes пути ≠ коду. ProcessorHealthService — stub. Sentry без fingerprinting |

### Итерация 2: БД и Сервисы (6.3/10)

| Компонент | Балл | Ключевой факт |
|-----------|------|---------------|
| БД | 6/10 | Нет UnitOfWork. `alembic.ini` опечатка. MSSQL/MySQL/DB2 — фейк. Нет bulk ORM |
| Сервисы | 6/10 | `ai/` god package 24K строк. Lazy-import эпидемия. Blanket `except Exception` |
| Extensions | 6/10 | 1 реальный плагин. ~30 нарушений импортов. Sandbox мёртв. 2 loader'а |
| DSL | 7/10 | 300+ методов, hot-reload. WorkflowBuilder без `loop`/`invoke_workflow`. Дублирование примитивов |
| Логи/конфиг | 7/10 | Regex-only PII. Нет log sampling. Rate limiter fail-open при Redis outage |
| Отказоустойчивость БД | 7/10 | Нет `statement_timeout`. Retry не интегрирован в DB layer. Нет nested tx |

### Итерация 3: Фронт и API (6.4/10)

| Компонент | Балл | Ключевой факт |
|-----------|------|---------------|
| Фронтенд | 6/10 | Streamlit 65+ страниц flat. React MVP на mock'ах. Sync HTTP клиент |
| API Entrypoints | 8/10 | 16 протоколов. v2 мёртв. gRPC только unary. WS без auth. BASIC dummy |
| Multi-protocol | 7/10 | Единый dispatch_action. SOAP — ручная строковая склейка. GraphQL generic JSON |
| OpenAPI | 6/10 | FastAPI стандартный json (не orjson). DSL schema — `type: object`. Нет merged OpenAPI |
| Security | 5/10 | APIKeyMiddleware ломает per-client ключи. GlobalRateLimitMiddleware не зарегистрирован. Нет tenant-фильтра в repo |

### Итерация 4: DSL, Workflow, AI, RPA (6.3/10)

| Компонент | Балл | Ключевой факт |
|-----------|------|---------------|
| DSL роуты | 8/10 | Registry не потокобезопасен. Два hot-reload'ера. YAML-ошибки без line numbers |
| Workflow | 7/10 | Компилятор не поддерживает checkpoint/guardrail/escalate/reflect/gateway. Два YAML-формата |
| AI | 6.5/10 | 3 кодопути LLM. AIGateway pass-through default. In-memory хранилища в production. CPU-default ML |
| RPA | 6/10 | RPACallPolicy не проведена в процессоры. Desktop только 3 action. Нет Vault для RPA credentials |
| Интеграция слоёв | 5/10 | Нет propagation tenant/corr в workflow. Agent invoke нарушает Temporal sandbox. Нет защиты от циклов |

### Итерация 5: Документация, CI/CD, Зависимости (6.5/10)

| Компонент | Балл | Ключевой факт |
|-----------|------|---------------|
| Документация | 7/10 | 14k `.rst` в репо. Нет CONTRIBUTING.md. 649 docstring-нарушений. 20 ADR без статуса |
| CI/CD | 7/10 | Release dry-run. AI PR Review фикция. pytest-xdist не задействован. Bandit warn-only |
| Мёртвый код | 6/10 | `ai_processors.py` 1164 строк жив. Banking RPA stubs. Feature-flags просрочены |
| Зависимости | 6/10 | Core раздут (92 deps). `diskcache` с CVE. Три cache-библиотеки. Дубли в манифесте |
| Интеграции | 7/10 | Webhook outbound без retry/idempotency. Нет generated clients. NATS без CB |
| Тесты | 6/10 | Покрытие 51%. E2E пустые. 10 flaky. pytest-xdist не в CI. Нет factory-boy |

---

## 3. Топ-10 критических проблем (P0)

| # | Проблема | Итерация | Риск |
|---|----------|----------|------|
| 1 | **AIGateway в pass-through** — 3 кодопути обходят pipeline без policy/audit | 4 | Регуляторный, безопасность |
| 2 | **316 нарушений layer policy** — `get_logger` в infra размазан по всем слоям | 1,2 | Архитектурный |
| 3 | **Security middleware не подключены** — GlobalRateLimitMiddleware, SecurityHeadersMiddleware отсутствуют в цепочке | 3 | Безопасность |
| 4 | **Tenant isolation не работает** — SQLAlchemyRepository не фильтрует по tenant_id, middleware ставит "default" | 3 | Утечка данных |
| 5 | **Покрытие тестами 51%** при gate 75% — 25+ модулей без тестов | 5 | Регрессии |
| 6 | **Agent invoke нарушает Temporal sandbox** — прямой `await` в workflow-коде, nondeterminism replay | 4 | Потеря состояний |
| 7 | **Core зависимости раздуты** — `polars`, `duckdb`, `dask`, `motor`, `elasticsearch` в ядре | 5 | Время сборки, CVE |
| 8 | **Нет propagation контекста** — tenant_id/correlation_id/auth не передаются через роут→workflow→agent→tool | 4 | Невозможен audit, tracing разрывается |
| 9 | **Release pipeline фикция** — dry-run, semantic-release на `main` вместо `master` | 5 | Невозможен release |
| 10 | **AI PR Review фикция** — `print('PASS')`, все `continue-on-error` | 5 | Ложное спокойствие |

---

## 4. Топ-10 сильных сторон

| # | Сторона | Где |
|---|---------|-----|
| 1 | **16 протоколов entrypoints** — unified dispatch через ActionHandlerRegistry | entrypoints/ |
| 2 | **Resilience production-ready** — 11 fallback-цепочек, adaptive timeout, chaos tests | core/resilience/ |
| 3 | **Plugin runtime зрелый** — semver, capability-gate, topo-sort, hot-swap | core/plugin_runtime/ |
| 4 | **CI/CD enterprise-уровня** — 15 workflows, SBOM+cosign, toxiproxy chaos | .github/workflows/ |
| 5 | **Temporal integration** — client factory, worker pool, activity adapter, data converter | infrastructure/workflow/ |
| 6 | **HITL end-to-end** — SignalWait, HitlService, REST API, Streamlit UI | services/ops/hitl/ |
| 7 | **DI на svcs** — type-based + name-based lookup, lazy-import защита | core/svcs_registry.py |
| 8 | **Schema-registry lock-free** — 3 формата, snapshots, метрики | services/schema_registry/ |
| 9 | **Feature flags OpenFeature-compatible** — per-tenant, Redis broadcast, runtime override | core/feature_flags/ |
| 10 | **CLAUDE.md + ADR-driven** — лучший в классе ops-файл для AI-ассистентов, 52 ADR | .claude/, docs/adr/ |

---

## 5. Рекомендуемые библиотеки (из web search)

| Библиотека | Заменяет / Дополняет | Где применить |
|------------|----------------------|---------------|
| `pyresilience` | Самописный CB + retry + bulkhead | Единый декоратор вместо stack tenacity+purgatory+custom |
| `strawberry.experimental.pydantic` | Ручной маппинг GraphQL типов | Авто-генерация Strawberry типов из Pydantic |
| `context-async-sqlalchemy` | Ручное управление сессиями | Упрощение async SQLAlchemy контекстов |
| `rpaframework` | Самописные RPA процессоры | Robot Framework + Playwright для enterprise RPA |
| `loguru` / `logly` (Rust) | structlog fallback | Альтернатива для dev-режима (не prod) |
| `deptry` + `vulture` | Ручной аудит мёртвого кода | CI gate для unused imports и dependencies |

---

## 6. План будущих спринтов

### Sprint 37 — «Security & Layer Hardering» (2 недели)

**Цель:** Закрыть P0 security gaps и layer violations.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| FIX: Удалить/починить APIKeyMiddleware (order 110) — оставить только AuthRequiredMiddleware | 3 | Security |
| FIX: Зарегистрировать GlobalRateLimitMiddleware в setup_middlewares.py | 2 | Security |
| FIX: Зарегистрировать SecurityHeadersMiddleware (HSTS/CSP/X-Frame) | 2 | Security |
| FIX: Добавить tenant_id фильтр в SQLAlchemyRepository (mixin) | 5 | Core |
| FIX: Перенести `get_logger` из infrastructure в core/utilities | 5 | Core |
| FIX: Закрыть прямые импорты extensions→infrastructure через фасады | 8 | Extensions |
| CHORE: Починить K8s probes пути (deployment-app.yaml /ready /health) | 2 | DevOps |
| CHORE: Синхронизировать Helm UID 1000→10001 | 1 | DevOps |

**KPI:** 316 layer violations → <50. Security middleware 100% подключены.

---

### Sprint 38 — «AIGateway Enforcement & Context Propagation» (2 недели)

**Цель:** Включить AIGateway, починить tracing через слои.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| FEAT: `ai_gateway_enforce=True` default в prod.yml | 2 | AI |
| REFACTOR: Убрать `self._providers` из AIAgentService, делегировать в LiteLLMGateway | 5 | AI |
| FIX: `compile_agent_invoke_step` → `workflow.execute_activity` (Temporal sandbox) | 3 | Workflow |
| FIX: Propagation tenant_id/correlation_id/auth через роут→workflow→agent→tool | 5 | Core |
| FEAT: `InvocationChain` guard — max_depth 5, защита от циклов | 3 | Core |
| FIX: Temporal OTel interceptor + связь с DSL TracingMiddleware | 3 | Observability |
| FEAT: AIGateway OTel spans на каждый из 9 шагов | 3 | AI |
| CHORE: Удалить `ai_processors.py` (ADR-0102 closure) | 2 | DSL |

**KPI:** AIGateway pass-through = 0%. Tracing continuity 100% через слои.

---

### Sprint 39 — «Test Pyramid & Coverage» (2 недели)

**Цель:** Поднять покрытие с 51% до 65%, закрыть e2e-дыру.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| FEAT: Включить `pytest-xdist -n auto` в CI + разделить unit/integration jobs | 3 | CI |
| FEAT: Добавить `pytest-rerunfailures` + quarantine-файл для flaky | 3 | CI |
| FEAT: 5 e2e сценариев (SAML-flow, route CRUD, plugin lifecycle, credit_check, AI chat) | 8 | QA |
| FEAT: Добавить `factory-boy` + `faker`, заменить BaseFactory | 3 | Testkit |
| FEAT: Добавить `pytest-mock`, мигрировать DSL processor tests | 5 | Core |
| CHORE: Покрытие `entrypoints/soap`, `infrastructure/external_apis`, `services/io` | 8 | Core |
| CHORE: Починить 10 pre-existing flaky failures | 5 | Core |

**KPI:** Покрытие 65%. E2E 5+ тестов. 0 pre-existing flaky.

---

### Sprint 40 — «Dependency Diet & Dead Code Cleanup» (2 недели)

**Цель:** Сократить core deps, почистить мёртвый код.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| CHORE: Вынести `polars`, `duckdb`, `dask`, `motor`, `elasticsearch`, `qdrant-client`, `pypdf`, `markitdown`, `presidio-analyzer` в extras | 5 | Build |
| CHORE: Удалить `diskcache` (CVE), `aiocache` (POC) из core — оставить `cachetools` + Redis | 3 | Core |
| CHORE: Удалить `pybreaker` extra, `fastapi-limiter` — оставить `RedisRateLimiter` | 2 | Core |
| CHORE: Почистить дубли в `pyproject.toml` (pendulum ×2, presidio ×3) | 1 | Build |
| CHORE: Удалить `grpc-interceptor`, `cloudevents` (0 импортов) | 1 | Build |
| CHORE: Выпилить `ai_processors.py`, `_LegacyMultimodalRAGService`, legacy PluginLoader | 3 | Core |
| CHORE: Закрыть feature-flags с просроченными sunset (`api/v1`, `httpx_unified_transport`) | 2 | Core |
| CHORE: Удалить `ai-voice`, `fastembed-legacy` из pyproject.toml | 1 | Build |
| CHORE: Перегенерировать `uv.lock` | 1 | Build |

**KPI:** Core deps 92 → 60. 0 закомментированных extras. 0 просроченных sunset.

---

### Sprint 41 — «Workflow Completeness & RPA Hardening» (2 недели)

**Цель:** Дописать компилятор workflow, усилить RPA.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| FEAT: Step compilers для checkpoint, guardrail, escalate, reflect, gateway_* | 8 | DSL |
| FEAT: `loop()` и `invoke_workflow()` в WorkflowBuilder + spec | 5 | DSL |
| FEAT: DLQ для workflow (отдельная таблица/топик для max_attempts) | 3 | Workflow |
| FEAT: Автоматическая deadlock detection — метрики + алерт | 3 | Workflow |
| FIX: Консолидировать SagaLRAProcessor (persistent единственный) | 3 | DSL |
| FEAT: RPACallPolicy проведена в browser_pool + desktop_rpa_client | 3 | RPA |
| FEAT: Vault-фасад для RPA credentials | 3 | RPA |
| FEAT: Structured RPA audit trail | 3 | RPA |

**KPI:** Workflow compiler 100% шагов. RPA retry/DLQ работают в production.

---

### Sprint 42 — «Developer Experience & Documentation» (2 недели)

**Цель:** Onboarding < 1 час, документация = production-ready.

| Задача | Story Points | Owner |
|--------|-------------|-------|
| FEAT: `CONTRIBUTING.md` — setup, commit conventions, layer linter, pre-commit | 3 | Docs |
| CHORE: `docs/api/autoapi/` и `docs/_build/` в `.gitignore`, генерировать в CI | 2 | Docs |
| CHORE: Закрыть ADR-хвост (20 записей без статуса) | 2 | Arch |
| CHORE: Снизить docstring-allowlist 649 → 0 | 5 | Core |
| FIX: Исправить битые ссылки в tutorials | 1 | Docs |
| FEAT: C4/Mermaid-диаграммы в README | 2 | Docs |
| FEAT: `st.Page` + `st.navigation` в Streamlit (убрать числовые префиксы) | 3 | Frontend |
| FEAT: React: подключить реальные API + auth flow | 5 | Frontend |
| FEAT: Release pipeline — реальный PyPI publish, semantic-release на `master` | 3 | CI |
| FEAT: AI PR Review — реальные checks (llm-guard diff, inspect-ai) | 3 | CI |

**KPI:** Onboarding 4ч → 1ч. 0 битых ссылок. 100% ADR со статусом. Release = real.

---

## 7. Итоговый вердикт

**Общая оценка: 6.38 / 10**

Проект `gd_integration_tools` — это **зрелая интеграционная платформа** с enterprise-архитектурой (16 протоколов, Temporal, multi-tenancy, AI/RAG, resilience), но находящаяся в фазе **«почти production-ready»** с существенным tech-debt.

**Главный парадокс:** архитектура спроектирована на 8–9/10, а исполнение — на 5–6/10. Разрыв между «нарисованной» Clean Architecture и реальными импортами, между декларированными feature-flags и их реальным статусом, между CI pipeline и его реальной блокирующей силой — это системная проблема.

**Один главный шаг для +2 балла:** закрыть 316 нарушений layer policy (начать с `get_logger` + фасады для extensions) + включить AIGateway enforcement.

**Прогноз:** при следовании плану Sprint 37–42 (12 недель) проект достигнет уверенного **8.0/10** и будет готов к production signoff.
