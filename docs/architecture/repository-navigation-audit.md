# Repository Navigation Audit — 2026-09-11

> Метод: 6 параллельных read-only аналитиков (Core, DSL, Entrypoints,
> Services/Infrastructure, AI/Extensions, Docs/IA) + спот-верификация
> ключевых утверждений координатором. База: commit `9f32d8b0b` + fix-коммиты
> `4ed38d49c`, `5d093da13`, `029e8793d` (см. `docs/roadmap/CURRENT_BASELINE.md`).
> Каждое утверждение проверено grep/diff/ls по фактическому HEAD.
> Вердикты: KEEP / CONSOLIDATE / MOVE / DEPRECATE / DELETE_CANDIDATE / SPLIT / NO_ACTION.

## 1. Top-level каталоги

| Каталог | Размер | Назначение | Вердикт |
|---|---|---|---|
| `src/` | 100M | Ядро шины (backend + frontend/streamlit) | KEEP |
| `tests/` | 131M | Тесты (17504 collected) | KEEP |
| `docs/` | 13M / 911 .md | Документация (см. §4) | KEEP (с консолидацией) |
| `tools/` | 4.2M | CI-гейты и утилиты (`check_layers.py`, `check_coverage_gate.py`, …) | KEEP |
| `extensions/` | 1.7M | Бизнес-плагины (8 шт., `plugin.toml`; правило импортов соблюдено — 0 нарушений) | KEEP |
| `testkit/` | 772K | pytest11-плагин, fixtures, recorder/cassette | KEEP |
| `routes/` | 100K | DSL-роуты; 7/7 имеют `route.toml` | KEEP |
| `config_profiles/` | 56K | 6 YAML-профилей (base/dev/dev_light/mcp_clients/prod/staging) | KEEP |
| `ops/`, `deploy/`, `config/`, `dashboards/`, `make/`, `scripts/`, `ai_policies/`, `artifacts/` | <1M | Ops/CI/политики | KEEP |
| `plugins/` (корень) | — | `example_plugin/` со **старым `plugin.yaml`** + пустой `tools/` | CONSOLIDATE → `extensions/example_plugin` (там уже есть `plugin.toml`) |
| `.security/` | 20K | cosign/sbom policies, zap-rules, pip-audit allowlist | KEEP |
| `.worktrees/` | пустая, gitignored | — | DELETE_CANDIDATE (локальный мусор) |
| `graphify-out/`, `logs/`, `dist/`, `__pycache__/`, `*.egg-info/`, `var/` | 220M+ | gitignored, регенерируемые | NO_ACTION (не в git) |
| `profiles/`, `sdk/` (корень) | — | НЕ СУЩЕСТВУЮТ (профили — `config_profiles/`; SDK — `src/backend/sdk`) | NO_ACTION (не создавать) |

## 2. Спорные подпакеты src/backend/

| Путь | Ответственность (факт) | Public API / Inbound | Дубль/аналог | Вердикт |
|---|---|---|---|---|
| `core/api/` | Canonical public facade (cycle 29), 8 модулей | 128 импортёров | — | **KEEP** (единственный supported вход для extensions) |
| `core/facades.py` | Compat-shim `core.api import *`, «NEVER use in new code» | Прод-inbound 0; жив только self-тестом `tests/unit/core/test_facades_shim.py` | `core/api` | **DEPRECATE** (по плану cycle 241; удаление — следующий release cycle) |
| `core/frontend_facade.py` | Re-export core.* + `services.dsl_portal` | 9 streamlit-страниц + 4 arch-теста-стража | — | **KEEP** (SPLIT: вынос из core при следующем рефакторинге — единственное санкционированное core→services ребро) |
| `core/services/` | Lazy `__getattr__`-прокси к `services.core.*` + **`base_external_api.py` — байт-в-байт дубль `services/core/base_external_api.py` (275 строк, diff молчит)** | Прокси: 2 импортёра; дубль: 0 | `services/core/` | **DELETE_CANDIDATE** дубль `base_external_api.py`; сам прокси-пакет KEEP |
| `core/clients/` | 2 capability-facade (jupyter_hub, pool_health) через DI locator | 3 импортёра | concrete — в `infrastructure/clients/` | KEEP (Protocol/facade в core — корректно) |
| `core/workflow/` vs `dsl/workflow/` | core: Protocol+Fake (ADR-045); dsl: runtime (compiler/orchestrator) | core: 35 импортёров; dsl: 47 | — | KEEP оба (contracts vs runtime — разделение выдержано) |
| `core/dsl/` vs `dsl/` | core: protocols/variables (893 строки, Protocol-инверсия S115); dsl: engine/builders | core: 10 | — | KEEP оба |
| `core/runtime/registries` | **НЕ СУЩЕСТВУЕТ** (ни пути, ни упоминаний). Живые registries — top-level: `providers_registry.py`, `svcs_registry.py` (31 импортёр через sdk.get_service), `workflow_registry.py` | — | — | NO_ACTION (мифический путь из старой документации) |
| `src/backend/plugins/` | Только `composition/` (composition-root: app_factory, di, setup_*) — плагинов нет | composition-root app | имя конфликтует с extensions/plugins | **MOVE** → переименовать в `composition/` (следующий release cycle, с re-export shim) |
| `src/backend/ai/` | Тонкая policy-прослойка + `rag/docs_indexer.py` — **пустой stub-дубль** реального `services/ai/rag/docs_indexer.py` (399 строк) | мало | `services/ai/` | **CONSOLIDATE** → policy в `core/ai`, stub удалить |
| `services/workflows/hitl_signal_store_redis.py` | Полноценный Redis-адаптер (WATCH/pubsub) в application-слое; инфра уже реэкспортирует его | инфра-реэкспорт | `infrastructure/clients/storage/redis/` | **MOVE** → infrastructure |
| `services/ops/health.py:444` | Прямой `redis.asyncio.Redis(...)` мимо фасада `get_redis_client` | — | infra-фасад | **CONSOLIDATE** |
| `infrastructure/messaging/dlq/policy_resolver.py` | Hard-code бизнес-классификация (financial/analytics/operational) | — | `core/messaging/dlq_policy` | **MOVE** → core/messaging |
| `infrastructure/messaging/dlq/cleanup_job.py` (+lifecycle) | Retention-политика + APScheduler-оркестрация в инфре | — | `services/ops` | **MOVE** → services/ops |

## 3. DSL-домен (`src/backend/dsl/`)

| Позиция | Факт | Вердикт |
|---|---|---|
| `dsl/setup.py` | `bootstrap_dsl` не вызывается нигде в src/extensions (только тест) | **DELETE_CANDIDATE** |
| `dsl/audit_versioning.py` (368 LOC) | 0 прод-импортов, жив только тестами | **DEPRECATE** |
| `dsl/macros.py` | Задокументированный shim; `templates_library.py:148,162` ещё на нём | **DEPRECATE** (перевести templates_library на `dsl.blueprints`) |
| `dsl/orchestration/__init__.py` scaffold (Sensor/Backfill/DryRun/HITL) | Прод-потребителей нет (только тесты); `triggers.py` в том же пакете — живой (10 import-сайтов) | **DEPRECATE** scaffold; пакет переименовать (`route_triggers/`) для снятия коллизии имён с `workflow/orchestrator*` |
| `engine/processors/ai/banking_processors/base.py` | Остаток миграции в `ai_banking/`, 0 внешних импортов, нет `__init__` | **DELETE_CANDIDATE** |
| Три пары дублей процессоров: PlanExecute (287 vs 386 LOC), ReflectionLoop (233 vs 379), SagaLRA (398 vs 834/6 файлов) | Независимые реализации с живыми потребителями по обе стороны (`builders/base/__init__.py:89`, `builders/agent_dsl/orchestration.py:263`) | **CONSOLIDATE** (отдельная волна, миграция builders-колл-сайтов) |
| `FileWatchProcessor` — одно имя класса, два механизма | `engine/processors/file_watch.py` (watchdog, importlib-строка из `file_sources_mixin.py:117`) vs `rpa/operations/filewatchprocessor.py` (threading) | **SPLIT** (развести имена) |
| `workflow/` vs `orchestration/` | Разные домены (durable-workflow vs триггеры), дубля нет | KEEP (переименование — см. выше) |
| `blueprints/` + `blueprint_loader.py` + `templates_library.py` | Каталог+загрузчик+второй каталог шаблонов | KEEP loader; **CONSOLIDATE** шаблонных каталогов (долгосрочно) |
| `engine/processors/ai_processors.py` | Back-compat shim (ADR-0102), удаление запланировано | **DEPRECATE** по плану S84+ |

## 4. Documentation

| Позиция | Факт | Вердикт |
|---|---|---|
| mkdocs nav `API Reference: api/` | `docs/api/` **НЕ СУЩЕСТВУЕТ** — секция сайта мертва (mkdocstrings с `paths: [src]` настроен) | **FIX** nav (генерация API reference или убрать пункт) |
| `docs/workflow/` vs `docs/workflows/` | workflow/: 1 файл (versioning D172); workflows/: обзор. Nav ведёт только в `workflows/` | **CONSOLIDATE** → `workflows/` |
| `docs/migration/` vs `docs/migrations/` | Два документа об одном WAF Phase-2 (`waf-phase-2.md` vs `waf-phase2.md`). Nav — `migration/` | **CONSOLIDATE** |
| `docs/docs/` | Не stray-docs: `.vale.ini` + стили + словари | **MOVE** → `.vale/` (вводящее в заблуждение имя) |
| `docs/sprints/` + `docs/retros/` + `SPRINT_171_*.md` в корне docs/ | Снапшоты распылены по 3+ местам | **CONSOLIDATE** (одно место для sprint-снапшотов) |
| `docs/audit/` | 118 файлов / 6.8M (52% объёма docs), датированные снапшоты | **CONSOLIDATE** в archive-зону / чистка по расписанию |
| README.md | «114 actions, 12 files» vs ARCHITECTURE.md «35+ actions» — противоречие; sprint-снапшоты в evergreen-секции; пути `/sse/*`, `/webhook/*` не совпадают с фактическими `/events`, `/webhooks` | **DOC-FIX** |
| ARCHITECTURE.md | «синхронизация 2026-08-19» при mtime 2026-09-10; line-precise ссылка `CLAUDE.md:612` | **DOC-FIX** |
| CLAUDE.md | 4 битых пути: `PLAN.md`, `/root/.claude/plans/foamy-puzzling-dragonfly.md`, `gap-analysis/`, `graphify-out/wiki/index.md` | **DOC-FIX** (PLAN.md объявлен «источником правды», но не существует) |
| AGENTS.md | «Текущая фаза Sprint 36 (→2026-08-31)» истекла; два счётчика спринтов (36 и 171) в одном файле | **DOC-FIX** |

## 5. Entrypoints (протоколы)

17 подпакетов = «17 протоколов» README.md:385 — сходится. Регистрация — `plugins/composition/app_factory.py`.

| Вердикт | Объекты |
|---|---|
| KEEP | api, graphql, grpc, soap, websocket, sse (`/events`), webhook (`/webhooks`), mcp, cdc, asyncapi, stream, express, filewatcher (`/watchers`), http3 |
| CONSOLIDATE | mqtt: inbound `MqttHandler` в `app.state`, **0 потребителей**, в lifespan не стартует (жив только aiomqtt-sink) |
| DEPRECATE | `entrypoints/email/` (runtime-dead, заменён `infrastructure/sources/email.py`), `entrypoints/scheduler/` (test-only), `middlewares/admin_audit.py`, `middlewares/observability.py` (orphan, BaseHTTPMiddleware несовместим с pure-ASGI цепочкой) |
| Security-review | express: нет per-route auth/signature; gRPC: AuthInterceptor не ставится без `settings.secure.api_key` (смягчено unix-socket default); `/grpc` proto_viewer без per-route auth |

## 6. Слои (import direction)

- `tools/check_layers.py`: **0 новых нарушений**, baseline 14 legacy (`tools/check_layers_allowlist.txt`; 1 запись stale — чекер предлагает `--update-allowlist`).
- Направление core→infrastructure выдержано: 43 raw-grep-хита = TYPE_CHECKING/docstring-ложные + санкционированные facade-исключения.
- Blind spot чекера: ~29 файлов (entrypoints/mcp, streamlit) skip'аются как SyntaxError «multiple exception types must be parenthesized» — PEP-758 синтаксис, который чекер парсит старым AST. Требует фиксации парсера чекера на 3.14.

## 7. Целевая логика для нового разработчика (фактическая, без оговорок)

```text
Добавить протокол?            → entrypoints/<protocol>/ + app_factory.py
Добавить business use case?   → services/<domain>/ или extensions/<name>/
Добавить DSL-примитив?        → dsl/engine/processors/ (@processor) или dsl/builders/
Внешний adapter?              → infrastructure/<area>/
Контракт/Protocol?            → core/<domain>/ (Protocol+Fake)
Canonical import?             → core/api/ (НЕ core/facades.py)
Plugin extension?             → extensions/<name>/ + plugin.toml
Документация?                 → docs/<тип>/ (audit/roadmap — только снапшоты)
```

Все строки разрешаются без оговорок, кроме двух задокументированных исключений:
`core/frontend_facade.py` (core→services, охраняется arch-тестами) и
`core/api/*` facade-файлов (санкционированные инфраструктурные реэкспорты).

## 8. Топ проблем (приоритет)

1. **P1 — байт-в-байт дубль** `core/services/base_external_api.py` (бизнес-логика в core, 0 импортёров) → удалить в следующем release cycle после повторной проверки.
2. **P1 — битые ссылки в мета-доках**: mkdocs `api/`, CLAUDE.md ×4, README-протоколы (`/events` vs `/sse`).
3. **P2 — тройная терминология plugin**: `extensions/` (реальные) + корневой `plugins/` (legacy yaml) + `src/backend/plugins/` (composition без плагинов).
4. **P2 — тройной дубль AI-процессоров** (PlanExecute/ReflectionLoop/SagaLRA).
5. **P3 — docs-снапшотное загрязнение** (docs/audit 6.8M, sprint-файлы в 3 местах) + конфликт нумерации спринтов в флагманских доках.
