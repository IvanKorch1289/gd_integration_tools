# Итоговый отчёт V2: Deep Dive Audit `gd_integration_tools`

> Дата: 2026-06-09
> Метод: 8 итераций (5 explore-агентов + 3 shell-итерации) + web search
> Фактологическая база: точные строки кода, shell-метрики, AST-анализ
> Масштаб: 1653 Python-файлов, ~243k LOC (core+dsl+infra+services+entrypoints), 10,777 тестов

---

## 1. V1 vs V2: перепроверка выводов

| Вывод V1 | Статус V2 | Факт / Уточнение |
|----------|-----------|------------------|
| 316 layer violations | **Подтверждён** | `check_layers_allowlist.txt` = 316. **274 (86.7%)** — `get_logger` из `infrastructure.logging.factory`. Перенос в `core/logging.py` снимет 274 мгновенно |
| 361 layer violations (shell grep) | **Уточнён** | 361 включает `extensions/` и stale-метрики. Линтер (`check_layers.py`) видит 316 в `src/` |
| `get_logger` в infra ломает границы | **Подтверждён** | 52 файла в `core`, 159 в `services`, 61 в `entrypoints`, 2 в `frontend` импортируют `logging.factory` |
| extensions → infrastructure: 16 | **Уточнён** | **12** import-строк в 9 файлах (orders, files, orderkinds, users). Все тянут ORM-модели, session_manager, SQLAlchemyRepository |
| extensions → services: 20 | **Уточнён** | **14** import-строк в 9 файлах. BaseService, APISKBService, AdAuthError, BaseExternalAPIClient, MultiAgentSupervisor |
| APIKeyMiddleware ломает per-client ключи | **Уточнён** | Конфликт есть, но **не критичен**: AuthRequiredMiddleware (order 620) добавляется раньше через prepend и обрабатывает запрос ДО APIKeyMiddleware. Проблема — разные exclusion-списки и дублирование валидации |
| GlobalRateLimitMiddleware не зарегистрирован | **Подтверждён** | Отсутствует в `setup_middlewares.py`. Зарегистрированы 25 middleware, GlobalRateLimitMiddleware — не среди них |
| SecurityHeadersMiddleware не подключён | **Подтверждён** | Нет в `setup_middlewares.py` |
| SQLAlchemyRepository не фильтрует tenant_id | **Подтверждён** | `get()`, `count()`, `first_or_last()`, `add()`, `update()`, `delete()` — ни один не добавляет `.where(tenant_id == ...)` |
| Audit log client_id = anonymous | **Подтверждён** | `audit_log.py:63`: `getattr(request.state, "client_id", None)` — **ни один middleware не устанавливает** `request.state.client_id` |
| BlockedRoutesMiddleware exact match | **Подтверждён** | `blocked_routes.py:28`: `if request.url.path in blocked_routes:` — set, exact match, нет нормализации |
| Upload path traversal weak | **Подтверждён** | `files.py:138`: `.replace("/", "_")` — не защищает от `..`, `\`, `\x00` |
| `ai_gateway_enforce=False` default | **Подтверждён** | `features/sprints_24_27.py:86-88`: `default=False` |
| 3 кодопути LLM обходят AIGateway | **Подтверждён** | 1) `ai_agent.py:50-54,273-282` → `self._providers`; 2) `ai_graph.py:101-107,157-185` → `LiteLLMGateway`; 3) `agents_pydantic/base.py:156-162, adapter.py:79-80` → `LiteLLMGateway` |
| `compile_agent_invoke_step` sandbox violation | **Подтверждён** | `step_compilers.py:330-343`: `await gateway.invoke(request)` внутри workflow-функции. При `enforce=False` возвращает пустой `AIResponse` — шаг бесполезен |
| `_legacy_invoke` — пустой scaffold | **Подтверждён** | `gateway.py:219-232`: `del request; return AIResponse(content="", model_used="pass-through-scaffold")` |
| In-memory хранилища в production | **Подтверждён** | `MultimodalRAGService._collections: dict`, `AIWorkspaceManager._usage: dict`, `L3RetrievalGraphCache._store: dict` |
| alembic.ini опечатка | **Подтверждён** | `script_location = ./src/infrastructure/database/migrations` — нет `backend` |
| `pool_use_lifo` не прокидывается | **Подтверждён** | `database.py:181-201` — нет `pool_use_lifo` в `_engine_kwargs` |
| Нет UnitOfWork | **Подтверждён** | `repositories/base.py` — все методы с `@main_session_manager.connection()`, каждый открывает свою сессию |
| CDC backends — scaffold | **Подтверждён** | `poll_backend.py`: `yield` за `if False:`; `listen_notify_backend.py`: только `await self._stopped.wait()` |
| MSSQL/MySQL/DB2 — фейк | **Подтверждён** | В `_build_dsn` поддерживаются только `postgresql`, `oracle`, `sqlite` |
| pytest-xdist не в CI | **Подтверждён** | `test.yml:51-55` — нет `-n auto` |
| semantic-release на `main`, ветка `master` | **Подтверждён** | `pyproject.toml:868`: `branch = "main"`. Репозиторий — `master` |
| ZAP без backend | **Подтверждён** | `zap.yml` — нет шагов запуска приложения, target `localhost:8000` |
| 3 AI checks — `print('PASS')` | **Подтверждён** | `ai-pr-review.yml:73,76,79` — `print('Layer policy check: PASS')` и т.д. |
| Release — dry-run | **Подтверждён** | `release.yml:20`: `release-dry-run`; `pyproject.toml:869-870`: `upload_to_pypi = false`, `upload_to_release = false` |
| Core deps 92 | **Опровергнуто** | **115** строк в dependencies (счёт через grep) |
| `diskcache` с CVE | **Подтверждён** | `pyproject.toml:61`: комментарий «NO FIX for CVE-2025-69872» |
| `ai-voice`, `fastembed-legacy` закомментированы | **Подтверждён** | Строки 218-228, 256-268 в `pyproject.toml` |

---

## 2. Новые критические находки V2 (не обнаруженные в V1)

| # | Находка | Файл | Строки | Риск |
|---|---------|------|--------|------|
| N1 | **DetachedInstanceError в `update()`** — `update` вызывает `self.get()` в другой сессии | `repositories/base.py` | 360, 380 | Data corruption |
| N2 | **SkillInvokeProcessor: `del context`** — ExecutionContext полностью игнорируется | `dsl/engine/processors/agent_dsl/skill_invoke.py` | 76-87 | Потеря tenant/auth/trace |
| N3 | **Middleware order inverted** — высокий order = outermost (через prepend), комментарий утверждает обратное | `registry.py` | ~31 | Путаница в поддержке |
| N4 | **S3-ключи не валидируются** — `file_uuid` из path/query передаётся напрямую в S3Service | `files.py`, `s3_pool.py` | 157-217 | Path traversal в S3 |
| N5 | **240 feature flags, 224 default=False** — «мертвый лес» флагов | `core/config/features/` | — | Complexity, tech debt |
| N6 | **Graceful shutdown без HTTP drain** — Uvicorn без `timeout_graceful_shutdown` | `main.py`, `lifecycle.py` | 44-71, 1015 | Прерывание in-flight запросов |
| N7 | **Temporal OTel interceptor отсутствует** — tracing через workflow — чёрный ящик | `infrastructure/workflow/` | — | Невозможен distributed trace |
| N8 | **SLO enforcement не реализован** — только метрики, нет отклонения запросов | `slo_tracker.py` | 102-136 | Нет защиты от degradation |

---

## 3. Обновлённые оценки по итерациям

| Итерация | V1 | V2 | Δ | Обоснование изменения |
|----------|-----|-----|---|----------------------|
| 1. Инфраструктура | 6.4 | **6.2** | -0.2 | Middleware order inverted (N3), S3 key validation (N4) |
| 2. БД и сервисы | 6.3 | **6.0** | -0.3 | DetachedInstanceError (N1), 115 core deps (было 92), alembic.ini bug |
| 3. Фронт и API | 6.4 | **6.3** | -0.1 | Уточнение APIKeyMiddleware conflict (не критичен, но дублирование есть) |
| 4. DSL, Workflow, AI | 6.3 | **6.0** | -0.3 | `del context` в SkillInvokeProcessor (N2), 240 feature flags (N5) |
| 5. Документация, CI/CD | 6.5 | **6.3** | -0.2 | Graceful shutdown без drain (N6), SLO без enforcement (N8) |
| **ИТОГО** | **6.38** | **6.16** | **-0.22** | V2 строже и фактологически точнее |

**Доверительный интервал V2:** 5.9–6.5

---

## 4. Топ-10 критических проблем (обновлённый P0)

| # | Проблема | Файл | Итерация |
|---|----------|------|----------|
| 1 | **AIGateway в pass-through** + 3 обхода + `_legacy_invoke` пустой | `ai_agent.py`, `ai_graph.py`, `agents_pydantic/`, `gateway.py` | 3, 4 |
| 2 | **`compile_agent_invoke_step` нарушает Temporal sandbox** | `step_compilers.py:330-343` | 4 |
| 3 | **274 layer violations из `logging.factory`** — 86.7% всех violations | `infrastructure/logging/factory.py` | 1 |
| 4 | **DetachedInstanceError в `update()`** — cross-session bug | `repositories/base.py:360,380` | 4 |
| 5 | **Security middleware gaps** — GlobalRateLimit, SecurityHeaders не подключены | `setup_middlewares.py` | 2 |
| 6 | **Tenant isolation не работает** — SQLAlchemyRepository без auto-filter | `repositories/base.py` | 2 |
| 7 | **SkillInvokeProcessor: `del context`** — полная потеря контекста | `skill_invoke.py:76-87` | 8 |
| 8 | **Audit log client_id = "anonymous"** — compliance невозможен | `audit_log.py:63` | 2 |
| 9 | **Release pipeline сломана** — semantic-release на `main`, ветка `master` | `pyproject.toml:868` | 5 |
| 10 | **Graceful shutdown без HTTP drain** — in-flight запросы прерываются | `main.py`, `lifecycle.py` | 8 |

---

## 5. Топ-10 сильных сторон (без изменений от V1)

1. **16 протоколов** — unified dispatch через ActionHandlerRegistry
2. **11 fallback-цепочек resilience** — adaptive timeout, chaos tests, SelfHealer
3. **Plugin runtime** — semver, capability-gate, topo-sort, hot-swap
4. **15 CI workflows** — SBOM+cosign, toxiproxy chaos
5. **Temporal integration** — client factory, worker pool, activity adapter
6. **HITL end-to-end** — SignalWait, HitlService, REST API, Streamlit UI
7. **DI на svcs** — type-based + name-based lookup
8. **Schema-registry lock-free** — 3 формата, snapshots, метрики
9. **Feature flags OpenFeature-compatible** — per-tenant, Redis broadcast
10. **CLAUDE.md + ADR-driven** — лучший ops-файл для AI-ассистентов, 52 ADR

---

## 6. Обновлённый план спринтов (Sprint 37–43)

### Sprint 37 — «Critical Fixes» (2 недели)
**Цель:** Закрыть P0 bugs, которые ломают данные или безопасность.

| Задача | SP | Owner |
|--------|-----|-------|
| FIX: AIGateway `ai_gateway_enforce=True` default в prod + убрать `_legacy_invoke` | 3 | AI |
| FIX: `compile_agent_invoke_step` → `workflow.execute_activity` | 3 | Workflow |
| FIX: `repositories/base.py` — `update()` не вызывать `self.get()` в другой сессии (use `merge` или same session) | 3 | Core |
| FIX: Перенести `get_logger` + `LoggerProtocol` в `core/logging/` (274 violations) | 5 | Core |
| FIX: `SkillInvokeProcessor` — убрать `del context`, пробросить tenant/corr | 2 | DSL |
| FIX: `audit_log.py` — читать `request.state.auth.principal` вместо `client_id` | 1 | Security |
| FIX: `alembic.ini` — добавить `backend` в `script_location` | 1 | DevOps |
| FIX: `database.py` — добавить `pool_use_lifo` в `_engine_kwargs` | 1 | Core |

**KPI:** 274 violations закрыты. 0 detached object bugs. AIGateway enforcement 100%.

---

### Sprint 38 — «Security Hardening» (2 недели)
**Цель:** Подключить missing middleware, fix tenant isolation.

| Задача | SP | Owner |
|--------|-----|-------|
| FIX: Зарегистрировать `GlobalRateLimitMiddleware` в `setup_middlewares.py` | 2 | Security |
| FIX: Зарегистрировать `SecurityHeadersMiddleware` | 2 | Security |
| FIX: Добавить auto-tenant filter в `SQLAlchemyRepository` (mixin/базовый класс) | 5 | Core |
| FIX: `BlockedRoutesMiddleware` — prefix match + path нормализация | 2 | Security |
| FIX: Upload — полная санитизация filename (path traversal, null bytes, control chars) | 3 | Security |
| FIX: S3 key validation в `S3Service` / `S3Client` | 2 | Security |
| CHORE: Удалить `APIKeyMiddleware` или синхронизировать с `AuthRequiredMiddleware` | 3 | Security |
| FIX: `semantic-release` branch `main` → `master` | 1 | DevOps |

**KPI:** Все security middleware подключены. Tenant isolation работает auto.

---

### Sprint 39 — «Context & Tracing» (2 недели)
**Цель:** Пробросить контекст через все границы, включить tracing.

| Задача | SP | Owner |
|--------|-----|-------|
| FIX: `InvokeWorkflowProcessor` — добавить tenant_id/correlation_id/traceparent в `start_workflow` | 3 | Workflow |
| FIX: `emitter.py` — прокинуть tenant/corr/trace в `ctx` | 2 | Workflow |
| FIX: `SkillRegistry.invoke` — добавить optional `context` аргумент | 3 | Core |
| FEAT: `InvocationChain` guard — max_depth 5, защита от циклов | 3 | Core |
| FEAT: Temporal OTel interceptor + связь с DSL TracingMiddleware | 5 | Observability |
| FEAT: AIGateway spans на 9 шагов pipeline | 3 | AI |
| FEAT: HTTP drain в graceful shutdown + Uvicorn `timeout_graceful_shutdown` | 3 | DevOps |

**KPI:** Tracing continuity 100% через слои. 0 разрывов контекста.

---

### Sprint 40 — «Tests & Coverage» (2 недели)
**Цель:** Поднять покрытие, закрыть e2e, ускорить CI.

| Задача | SP | Owner |
|--------|-----|-------|
| FEAT: `pytest-xdist -n auto` в CI + разделить unit/integration jobs | 3 | CI |
| FEAT: `pytest-rerunfailures` + quarantine-файл | 3 | CI |
| FEAT: 5 e2e сценариев (SAML, route CRUD, plugin lifecycle, credit_check, AI chat) | 8 | QA |
| FEAT: `factory-boy` + `faker` | 3 | Testkit |
| FEAT: `pytest-mock`, миграция DSL processor tests | 5 | Core |
| CHORE: Покрытие `entrypoints/soap`, `infrastructure/external_apis`, `services/io` | 8 | Core |
| CHORE: Починить 10 pre-existing flaky | 5 | Core |

**KPI:** Покрытие 65%. E2E 5+ тестов. CI time -40%.

---

### Sprint 41 — «Dependency Diet & Dead Code» (2 недели)

| Задача | SP | Owner |
|--------|-----|-------|
| CHORE: Вынести `polars`, `duckdb`, `dask`, `motor`, `elasticsearch`, `qdrant-client`, `pypdf`, `markitdown`, `presidio-analyzer` в extras | 5 | Build |
| CHORE: Удалить `diskcache` (CVE), `aiocache` (POC) из core | 3 | Core |
| CHORE: Удалить `pybreaker` extra, `fastapi-limiter` | 2 | Core |
| CHORE: Удалить `grpc-interceptor`, `cloudevents` (0 импортов) | 1 | Build |
| CHORE: Выпилить `ai_processors.py` (ADR-0102 closure) | 2 | DSL |
| CHORE: Удалить `_LegacyMultimodalRAGService`, legacy PluginLoader | 2 | Core |
| CHORE: Закрыть просроченные feature-flag sunset (`api/v1`, `httpx_unified_transport`) | 2 | Core |
| CHORE: Удалить `ai-voice`, `fastembed-legacy` из pyproject.toml | 1 | Build |

**KPI:** Core deps 115 → 70. 0 закомментированных extras. 0 просроченных sunset.

---

### Sprint 42 — «Workflow & RPA Completeness» (2 недели)

| Задача | SP | Owner |
|--------|-----|-------|
| FEAT: Step compilers для checkpoint, guardrail, escalate, reflect, gateway_* | 8 | DSL |
| FEAT: `loop()` и `invoke_workflow()` в WorkflowBuilder | 5 | DSL |
| FEAT: DLQ для workflow (таблица/топик для max_attempts) | 3 | Workflow |
| FEAT: Автоматическая deadlock detection | 3 | Workflow |
| FIX: Консолидировать SagaLRAProcessor (persistent единственный) | 3 | DSL |
| FEAT: RPACallPolicy в browser_pool + desktop_rpa_client | 3 | RPA |
| FEAT: Vault-фасад для RPA credentials | 3 | RPA |
| FEAT: Structured RPA audit trail | 3 | RPA |

**KPI:** Workflow compiler 100% шагов. RPA retry/DLQ работают.

---

### Sprint 43 — «Developer Experience» (2 недели)

| Задача | SP | Owner |
|--------|-----|-------|
| FEAT: `CONTRIBUTING.md` | 3 | Docs |
| CHORE: `docs/api/autoapi/` в `.gitignore`, генерировать в CI | 2 | Docs |
| CHORE: Закрыть ADR-хвост (20 без статуса) | 2 | Arch |
| CHORE: Docstring allowlist 649 → 0 | 5 | Core |
| FIX: Исправить битые ссылки в tutorials | 1 | Docs |
| FEAT: C4/Mermaid-диаграммы в README | 2 | Docs |
| FEAT: Streamlit `st.Page` + `st.navigation` | 3 | Frontend |
| FEAT: React: реальные API + auth | 5 | Frontend |
| FEAT: Release pipeline — real PyPI publish | 3 | CI |
| FEAT: AI PR Review — real checks (llm-guard diff) | 3 | CI |

**KPI:** Onboarding < 1ч. 0 битых ссылок. Release = real.

---

## 7. Итоговый вердикт V2

**Общая оценка: 6.16 / 10** (V1: 6.38)

V2 оценка **ниже** V1, потому что:
1. Более строгая фактологическая проверка обнаружила новые критичные баги (DetachedInstanceError, `del context`, middleware order inversion)
2. Shell-метрики показали большее раздутие (115 core deps вместо 92, 240 feature flags)
3. Агенты с точными файловыми ссылками подтвердили, что многие «production-ready» компоненты — scaffold'ы или имеют критичные баги

**Главный парадокс усилился:** архитектура спроектирована на 8–9/10, но исполнение на 4–5/10. Разрыв между «нарисованной» Clean Architecture и кодом — системная проблема.

**Один главный шаг для +2 балла:** закрыть 274 `logging.factory` violations + включить AIGateway enforcement + починить DetachedInstanceError.

**Прогноз:** при следовании плану Sprint 37–43 (14 недель) проект достигнет **7.8/10** и будет готов к production signoff.
