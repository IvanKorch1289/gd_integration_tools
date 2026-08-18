# Contributing to gd_integration_tools

> Краткое руководство для будущих пользователей-разработчиков проекта.
> Подробная архитектура — в [ARCHITECTURE.md](ARCHITECTURE.md), план
> развития — в [PLAN.md](PLAN.md), текущее состояние спринтов — в
> [docs/audit/](docs/audit/).

## Принципы проекта

### 1. Архитектурные правила (`AGENTS.md`)

- **Слоистость**: `core` → `services` → `infrastructure` → `entrypoints` → `plugins`.
  Зависимости направлены строго вниз. `core` не зависит от `infrastructure`.
- **80% декларативно / 20% Python**: бизнес-логика — в YAML/TOML DSL,
  Python — только для интеграций. `manage.py` регистрирует action через
  `call_function('module:fn')` без обёрток.
- **Thin facades**: фасады в `core/facades.py` (D160) — единственная
  точка входа для cross-layer доступа. Не импортируйте `infrastructure/*`
  из `services/*` напрямую.
- **Ponytail/YAGNI**: минимальный fix, deletion > addition, boring > clever.
  Каждый коммит — атомарный с regression тестами.

### 2. Стиль кода (`AGENTS.md`)

- **Python 3.14+ syntax**: `int | str`, generic `class Foo[T]`, `match`-statements.
- **Type hints везде**: `mypy>=1.20.1` strict mode (см. `[tool.mypy]` в pyproject.toml).
- **Async-first**: `FastAPI`/`Temporal` workers. Никаких blocking I/O в async-контексте.
- **Pydantic модели**: `BaseModel`, `ConfigDict`, `Field` для DTO/схем.
- **Conventional commits**: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `perf:`.
  Russian-first messages, без emoji, atomic commits (одна логическая правка = один коммит).

### 3. Тестирование

- **Pytest markers**: `@pytest.mark.unit`, `.integration`, `.asyncio`.
- **Все PR с тестами**: `make test` перед коммитом.
- **Regression tests**: каждый bug fix добавляет test, воспроизводящий баг.
- **Coverage**: `make test-cov` — minimum 80% (D150 rule).

```bash
make test            # все тесты
make test-unit       # только unit
make lint            # ruff
make type-check      # mypy
make format          # ruff format
```

## Структура репозитория

```
src/
├── backend/
│   ├── core/              # foundational abstractions
│   │   ├── ai/            # PydanticAI client + skill registry
│   │   ├── auth/          # 5 providers (API key, JWT, OAuth, SAML, mTLS)
│   │   ├── resilience/    # tenacity + purgatory facades (D160)
│   │   ├── dsl/           # DSL variables
│   │   ├── security/      # PII, vault, sandbox
│   │   └── facades.py     # 17 thin facades (D160 consolidation)
│   ├── services/          # business logic
│   │   ├── ai/            # agents, RAG, multi-agent
│   │   ├── workflow/      # Temporal glue
│   │   └── routes/        # route DSL handlers
│   ├── dsl/               # 88K LOC — DSL engine
│   │   ├── builders/      # 14,945 LOC fluent builder (76 mixins)
│   │   ├── engine/        # 438 files — execution, validation
│   │   ├── workflow/      # 3,440 LOC — Temporal compiler
│   │   ├── orchestration/ # 5,500 LOC — Camel triggers
│   │   └── yaml_loader/   # 590 LOC — YAML→Pipeline
│   ├── entrypoints/       # 14 protocols (REST/GraphQL/gRPC/SOAP/WS/SSE/MCP/MQTT/CDC/...)
│   │   ├── api/v1/        # FastAPI routers
│   │   ├── graphql/       # Strawberry
│   │   ├── grpc/          # grpcio + 3 servicers + interceptor
│   │   ├── mcp/           # FastMCP
│   │   └── ...
│   ├── infrastructure/    # external integrations
│   │   ├── database/      # SQLAlchemy + Alembic
│   │   ├── workflow/      # Temporal backends (3 variants)
│   │   ├── clients/       # HTTP/Kafka/Redis/PG/etc.
│   │   └── ...
│   ├── plugins/           # composition
│   │   └── composition/   # app_factory, lifecycle, middleware setup
│   ├── middleware/        # 30+ ASGI middlewares
│   └── extensions/         # business extensions (credit_pipeline, etc.)
└── frontend/
    └── streamlit_app/     # 36+ pages developer portal
tests/                      # 1538 test files (~14,815 tests)
docs/audit/                 # cycle reports (cycle-200+, audit findings)
```

## Workflow для нового фикса / фичи

### 1. Изучить существующее

```bash
# Понять текущее состояние
git log --oneline -20
cat AGENTS.md
cat docs/audit/CYCLE-$(git log -1 --pretty=%H | head -c 7).md 2>/dev/null || true
```

### 2. Создать атомарную ветку (опционально)

```bash
git checkout -b cycle-XXX-short-desc
```

### 3. Сделать Ponytail-fix

- **Минимальный diff**: 1-line если возможно
- **Тесты FIRST или ATOMIC**: regression test для бага, smoke test для фичи
- **Lint + type-check**: `make format && make lint && make type-check && make test`
- **Следовать existing patterns**: посмотри соседние файлы в том же модуле

### 4. Commit

```bash
git add <files>
git commit -m "fix(<area>): <Russian-first description>

D-AUDIT-XXXXX (cycle YYY): <root cause analysis>

Root cause: <what was wrong>
Fix: <what was changed>

Tests: <new/updated tests>
Refs: <cycle-NNN or issue>
"
```

### 5. Report (если cycle-bound)

```bash
# Если работа — часть цикла (Sprint N cycle YYY)
cat > docs/audit/CYCLE-YYY-FEATURE.md <<EOF
# Cycle YYY — feature (YYYY-MM-DD)
<summary>
EOF
git add docs/audit/CYCLE-YYY-FEATURE.md
git commit -m "docs(audit): cycle YYY — feature report"
```

## Архитектурные Ponytail-wins (в работе)

Полный список в [docs/audit/CYCLE-220-PROJECT-ANALYSIS.md](docs/audit/CYCLE-220-PROJECT-ANALYSIS.md).
Топ-3 для следующих циклов:

1. **pg_runner_backend cleanup** (2,476 LOC, "non-production-grade") — удалить после `LiteTemporalBackend` maturity check
2. **HTTP transport consolidation** (~1,500 LOC) — flip `httpx_unified_transport` flag ON
3. **DSL builder mixins** (~1,000 LOC) — `register_processor` decorator + auto-discovery

## Где искать помощь

- **Архитектура**: [ARCHITECTURE.md](ARCHITECTURE.md) — структура, диаграммы, контракты
- **Спринты**: [docs/audit/](docs/audit/) — отчёты cycle-200+ (Sprints 30+)
- **Планы**: [PLAN.md](PLAN.md), [SPRINT_PLAN_9_10.md](SPRINT_PLAN_9_10.md), [PLAN_TO_9_10.md](PLAN_TO_9_10.md)
- **Правила проекта**: [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md)
- **Известные issues**: [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md) — индекс кода, [docs/audit/SYNTHESIS_2026-08-13.md](docs/audit/SYNTHESIS_2026-08-13.md) — synthesis

## Часто задаваемые вопросы

### Q: Как добавить новый action?

1. Создать функцию в `extensions/<name>/actions.py`:
   ```python
   @register_action(protocol="auto", tags=["my-domain"])
   def my_action(payload: MyPayload) -> MyResult:
       ...
   ```
2. Зарегистрировать в `extensions/<name>/__init__.py` через `register_actions()`.
3. Action автоматически появится во всех 14 протоколах через `EntryDiscovery`.

### Q: Как добавить новый middleware?

1. Создать класс в `src/backend/entrypoints/middlewares/<name>.py`:
   ```python
   class MyMiddleware:
       def __init__(self, app):
           self.app = app
       async def __call__(self, scope, receive, send):
           # pre-processing
           await self.app(scope, receive, send)
           # post-processing
   ```
2. Зарегистрировать в `entrypoints/middlewares/setup_middlewares.py`:
   ```python
   registry.register_builtin("my_middleware", MyMiddleware, order=NNN)
   ```
3. Добавить тест в `tests/unit/entrypoints/middlewares/test_my_middleware.py`.

### Q: Как добавить новый DSL processor?

1. Создать класс в `src/backend/dsl/engine/processors/<name>.py`:
   ```python
   from src.backend.dsl.engine.processors.base import BaseProcessor

   class MyProcessor(BaseProcessor):
       name = "my_processor"
       def __init__(self, config):
           self.config = config
       async def process(self, exchange):
           ...
           return exchange
   ```
2. Зарегистрировать в `dsl/engine/registry.py`:
   ```python
   from src.backend.dsl.engine.processors.my_processor import MyProcessor
   PROCESSOR_REGISTRY.register("my_processor", MyProcessor)
   ```
3. Использовать в YAML DSL: `processors: - type: my_processor; config: {...}`.

### Q: Почему cycle-NNN зависает или падает?

См. [docs/audit/CYCLE-220-PROJECT-ANALYSIS.md](docs/audit/CYCLE-220-PROJECT-ANALYSIS.md#8-known-issues-from-cycles-201-220) — known issues:
- NEW-3 MCP: mount path mismatch (cycles 215-218)
- gRPC Cython real RPC: requires Cython-patching (cycle 209+)
- pg_runner_backend: explicit "non-production-grade" marker

## Лицензия

Apache 2.0 (см. [LICENSE](LICENSE)).
