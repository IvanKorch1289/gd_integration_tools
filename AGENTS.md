# AGENTS.md — gd_integration_tools (для Kimi Code CLI)

> Краткий summary для Kimi Code. **Полный контекст проекта — в `CLAUDE.md`**
> (V22, синхронизирован с `PLAN.md` V22 FINAL). Этот файл — точка входа;
> при неоднозначности читай `CLAUDE.md` через `Read`.

---

## Проект

`gd_integration_tools` — **универсальное domain-agnostic ядро** интеграционной
шины на Python 3.14+ (Apache-Camel- и Airflow-style). Внутренний продукт банка.

Ключевые возможности:
- DSL: YAML + Python builder (Camel-style fluent);
- Workflow / orchestration: Temporal (default) + LiteTemporalBackend (dev_light);
- Multi-protocol auto-registration: один handler → REST + SOAP + XML + gRPC +
  GraphQL + MQ + WS + SSE + MCP + MQTT;
- Multi-backend gateways: PG↔Oracle↔MSSQL↔MySQL↔DB2; Redis↔KeyDB;
  S3↔MinIO↔LocalFS; Kafka↔RabbitMQ↔Redis Streams↔NATS;
- RPA, CDC, file-watcher, webhook source/sink;
- AI/RAG/agents с MCP-сервером (FastMCP) и AI Safety (workspace isolation);
- Multi-tenancy (TenantContext + per-tenant SLO/quotas);
- Developer portal на Streamlit (36+ страниц).

**Бизнес-логика — только в `extensions/<name>/`**, ядро domain-agnostic.

**80% декларативно (YAML/TOML) / 20% Python** — через `call_function('module:fn')`
без обёрток в Action.

---

## Текущая фаза

**Sprint 36 — Production Readiness (90%+)** (2026-08-18 → 2026-08-31).
Sprint 35 закрыт (5 волн: SBOM+cosign, OWASP ZAP, chaos, hypothesis, pip-audit).

`PLAN.md` V22 — источник правды по roadmap и архитектурным решениям.

**Sprint 171 (S170+): M5 Middleware audit complete (commit 60f96f9).**
- 30+ ASGI middleware inventoried + centralization: INN validation (3→1),
  body-hash (4→1)
- D136 scaffolding: `make new-middleware NAME=foo [--layer 1-4]`
- 4 new helpers: `with_timeout`, `retry_async`, `StreamingBodyHasher`,
  `ObservabilityMiddleware` facade
- Все в `src/backend/core/utils/` + `src/backend/entrypoints/middlewares/`
- См. `docs/middleware/MIDDLEWARE.md`

---

## Что читать сначала

1. `CLAUDE.md` — полные правила (читай при любой неоднозначности);
2. `PLAN.md` (V22) — текущий roadmap и архитектурные решения;
3. `graphify-out/...` (если есть) — индекс кода;
4. `ARCHITECTURE.md`;
5. `.claude/DECISIONS.md`, `.claude/KNOWN_ISSUES.md`.

**Не читай весь репозиторий без необходимости.** Связи — через
`graphify query/path/explain`.

---

## Архитектура — слои и их границы

```
src/frontend/streamlit_app/  ─►  src/backend/entrypoints/  ─►  src/backend/services/
        │                              (REST/SOAP/gRPC/         (core[5-7],
        │                               GraphQL/WS/SSE/          ai, integrations,
        │                               MQTT/MCP/CDC/...)       ops, execution,
        │                                                        plugins, ...)
        │                                                        │
        ▼                                                        ▼
    public API only                                     src/backend/core/ (Protocols,
                                                         interfaces, di, tenancy,
                                                         plugin_runtime, auth, ai,
                                                         net[WAF], messaging, scaling)
                                                                ▲
                                                                │ контракты
                                                                ▼
                                                 src/backend/infrastructure/ (db, cache,
                                                         storage, messaging, search,
                                                         audit, sources, sinks, repos,
                                                         resilience, observability,
                                                         secrets[Vault],
                                                         workflow[Temporal+Lite])
                                                                ▲
                                                                │ (через registries)
                                                                ▼
                                                 src/backend/dsl/ (route/, workflow/,
                                                         service/, contracts/, engine,
                                                         blueprints/[10 patterns R2])
```

**Бизнес-логика** — `extensions/<name>/` (отдельные плагины с `plugin.toml`).
Импортирует ТОЛЬКО `gd_integration_tools.core.*` + capability-checked фасады.
Прямой импорт из `infrastructure/*` / `services/*` запрещён.

**`routes/<name>/`** — DSL-routes как «лёгкие плагины» (V11.1a).

**`gd_integration_tools.testkit.*`** — тестовые утилиты.

**Лёгкие routes** — `route.toml` + `*.dsl.yaml` (steps[] любых типов).

### Капитальные элементы V22
- `BasePlugin + PluginLoader` (core/plugin_runtime/) — discovery + lifecycle
  + capability-gate;
- `RouteBuilder` (dsl/route/builder/) — Camel-style fluent:
  `.crud_*`, `.proxy()`, `.call_function()`, `.invoke_workflow()`,
  `.get_setting()`, `.validate_response()`, `.db_call_procedure()`;
- `WorkflowBuilder + Workflow DSL` — Temporal-шаги декларативно;
- `ActionDispatcher + ActionHandlerRegistry` — Service Activator + 6 invoke modes;
- `ProcessorRegistry` (R1) — `@processor` декоратор для плагинов;
- `Schema-registry` (R1, RAM) — JSON-Schema каталог для LSP/docs/AsyncAPI;
- `ResilienceCoordinator + BreakerPolicy` (R6) — устойчивость;
- `ServiceDSLRegistry` + `@service_dsl(crud=True)` — авто-CRUD;
- `AIToolAdapter` + `AIWorkspaceManager` (R4) — AI Safety.

---

## Правила работы

### Запрещено
- Читать `.env`, `.env.*`, `secrets/**`, `*.pem`, `*.key`, `*secret*`, `*token*`
  (закреплено permission rules в `.kimi-code/config.toml`);
- `git push`, `make push`, `make ship`, `make ship-release`,
  `make clean-all`, `rm -rf`, `pip install`, `poetry add`, `poetry remove` —
  всё под deny;
- Импорт `extensions/*` → `infrastructure/*` / `services/*` напрямую;
- Бизнес-логика вне `extensions/<name>/`;
- Изменения в lock-файлах без явного согласования (Sprint 36);
- Force-push, reset --hard, чистые merge-коммиты;
- Secrets в коде, логах, коммитах (только через Vault);
- PII в логах (`detect-secrets` в CI).

### Обязательно
- Type hints везде (Python 3.14+ синтаксис: `int | str`, generic `class Foo[T]`);
- Async-first (FastAPI/Temporal). Никаких blocking I/O в async-контексте;
- Pydantic модели для DTO/схем (`BaseModel`, `ConfigDict`, `Field`);
- Тесты pytest с markers (`@pytest.mark.unit`, `.integration`, `.asyncio`);
- `make lint && make type-check && make test` перед коммитом;
- `make format` (ruff) перед коммитом;
- Capability-checked фасады для cross-layer доступа;
- `graphify update .` после структурных изменений;
- Commit короткий, Russian-first, без эмодзи;
- Conventional prefix в коммите: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`,
  `test:`, `build:`, `ci:`, `perf:`;
- Атомарные коммиты (одна логическая правка = один коммит).

### Рекомендуется
- 80% декларативно (DSL) / 20% Python;
- Изучить существующий паттерн перед добавлением нового модуля
  (`graphify query` / `codebase-map` skill);
- План → стоп → ревью → согласование → следующий шаг;
- Финал работы — список задач (НЕ выдуманные улучшения).

### Стиль ответов
- Russian first, English second;
- Кратко, по делу, без воды;
- Варианты A/B/C/D вместо открытых вопросов;
- Без `emoji` в технических ответах без явной просьбы;
- Markdown только по делу.

---

## Ponytail mode (минимализм / YAGNI)

Активен по умолчанию для задач доработки кода. Правила взяты из
`.kimi-code/skills/ponytail/SKILL.md`. Приоритет: проектные архитектурные
ограничения (слоистость, фасады, async-first) остаются неприкосновенными.

**Лестница перед написанием кода:**

1. Нужно ли это вообще? (YAGNI) — спекулятивная потребность = пропустить.
2. Решает ли stdlib?
3. Решает ли уже установленная зависимость?
4. Можно ли сделать в одну строку?
5. Только потом — минимальный рабочий код.

**Правила:**

- Никаких ненужных абстракций: один implementation → не нужен интерфейс,
  один product → не нужна фабрика, неизменяемое значение → не нужен config.
- Никакого boilerplate/scaffolding "на потом".
- Deletion over addition. Boring over clever.
- Shortest working diff wins.
- Помечать намеренные упрощения комментарием `ponytail: ...`.
- Если shortcut имеет потолок (global lock, O(n²), naive heuristic) — комментарий
  должен называть предел и путь апгрейда.

**Уровни интенсивности:** `/skill:ponytail [lite|full|ultra]`.

**Не упрощать:** валидацию на границах доверия, обработку ошибок,
предотвращающую потерю данных, меры безопасности, accessibility, явно
запрошенный пользователем функционал, архитектурные правила проекта.

---

## Skills (slash-команды)

Kimi Code автоматически подхватывает:

**Из `.claude/skills/` (через `extra_skill_dirs`):**
- `codebase-map`, `plan-execute`, `verify-change`, `compact-session`,
  `connector-building`, `refactoring`, `workflow-engineering`,
  `feature-development`, `commit-work`, `research-current-tech`.

**Из `.kimi-code/skills/`:**
- `python-dev` — правила Python-разработки (этот проект);
- `code-review` — чеклист ревью изменений;
- `ponytail` — YAGNI / минимализм / "ленивый senior dev".

Формат вызова: `/skill:<name> [аргументы]`.

---

## MCP-серверы

Подключены в `.kimi-code/mcp.json`:
- `filesystem` — навигация по проекту;
- `sequential-thinking` — пошаговое планирование;
- `memory` — заметки между сессиями;
- `duckduckgo-search` — поиск в интернете;
- `context7` — актуальная документация библиотек (нужен `CONTEXT7_API_KEY`);
- `codeclone` — поиск похожего кода;
- `mako-ai` — AI-ассистент.

---

## Полный контекст

Если раздел выше неполон или устарел — **читай `CLAUDE.md`**. Он синхронизирован
с `PLAN.md` V22 FINAL и является source of truth для проекта.
