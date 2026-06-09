# Итерация 2: БД, сервисы, расширения, DSL, логирование

## 2.1 Слой БД — 6/10
**Плюсы:** Async-first SQLAlchemy, SmartSessionManager (read→replica, write→primary), pool warm-up, PoolMonitor, circuit breaker, alembic + Redis lock, slow query logging.
**Минусы:** `pool_use_lifo` не прокидывается в engine. `alembic.ini` — опечатка в пути (пропущен `backend`). Нет UnitOfWork — каждый repo открывает свою сессию. ORM-модели в `infrastructure/`, а не в `extensions/`. MSSQL/MySQL/DB2 — фейк (только в документации). CDC Poll/ListenNotify — scaffold. Нет bulk-операций в ORM. Нет `raiseload` защиты от N+1.

## 2.2 Сервисный слой — 6/10
**Плюсы:** Type hints везде, async-first, кастомные exceptions, execution middleware chain, adaptive timeout, хорошая документация (67% функций, 93% классов).
**Минусы:** `ai/` — god package (24K строк, 57% кода services/). Смешение DI-паттернов (app_state_singleton + ручные синглтоны + глобальные registry). Массовые lazy-imports внутри методов (костыль от циклических зависимостей). Длинные оркестраторы (`chat()` 148 строк, `_apply_rule()` 263 строк). Blanket `except Exception` в hot-path (Invoker, AIAgentService). Retry/CB практически отсутствуют в services/.

## 2.3 Расширения — 6/10
**Плюсы:** PluginLoaderV11 (TOML, topo-sort, semver), CapabilityGate (работает, покрыт тестами), ProcessorRegistry (@processor, JSON-Schema), hot-swap, lifecycle hooks.
**Минусы:** Только 1 реальный плагин (`credit_pipeline`), остальные — CRUD-заглушки. ~30+ нарушений импорта extensions→infrastructure/services. Два loader'а параллельно (legacy + V11). Sandbox (e2b) — мёртвый код (все плагины Tier-A). ProcessorRegistry не используется в extensions. Hot-swap грубый (все плагины). `test_plug` — артефакт.

## 2.4 DSL — 7/10
**Плюсы:** RouteBuilder 300+ методов, fluent API, WorkflowBuilder с saga/compensate, Exchange/Pipeline/ExecutionEngine зрелые, YAML-hot-reload (watchfiles, atomarный rescan), Schema-registry RAM-based production-ready, DSL-файлы читаемы.
**Минусы:** RouteBuilder раздут (20 миксинов, 430 определений). WorkflowBuilder неполный — нет `loop()` и `invoke_workflow()`. Дублирование примитивов (timeout/retry/saga/branching) между RouteBuilder и WorkflowBuilder. `_is_allowed_processor` через MRO-introspection — overhead. `BranchSpec.steps: list[Any]` — нетипизировано.

## 2.5 Логирование и конфигурация — 7/10
**Плюсы:** structlog + JSON, PII masking (email/phone/SNILS/INN/passport/card), correlation-id, batching sinks, Graylog/Sentry integration, multi-profile config (base+overlay), Pydantic validation, Vault integration, secrets audit.
**Минусы:** PII — regex-only, нет Presidio/NER в общем логировании. Нет log sampling/throttling. Rate limiter без Redis fallback = fail-open при outage. Deep merge списков — replace, не append. Route разбит на YAML+TOML. SLO — только метрики, нет enforcement.

## 2.6 Отказоустойчивость БД — 7/10
**Плюсы:** Pool warm-up, PoolMonitor, pool_pre_ping, ConnectionReuseManager, SmartSessionManager (lag-budget routing), retry tenacity + RetryBudget, circuit breaker, graceful shutdown sequence, SagaLRAProcessor, TransactionalClientProcessor (outbox).
**Минусы:** `pool_use_lifo` не прокинут. Нет `statement_timeout` PG. Retry не интегрирован в DB layer (cold-start падает сразу). Нет nested transactions/savepoints. Нет read-your-writes consistency. Нет HTTP drain в graceful shutdown. Много stub health-checks.

## Библиотеки из web search
- `context-async-sqlalchemy` — удобный контекстный менеджер для async SQLAlchemy
- SQLAlchemy 2.0 async patterns — рекомендуется `expire_on_commit=False`, `autoflush=False`
- `loguru` / `logly` (Rust-powered) — альтернативы structlog с проще API
