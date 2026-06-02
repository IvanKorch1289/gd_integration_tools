# BOOTSTRAP — единая точка входа для Claude Code и Kimi Code

> **V22 Sprint 37 W1** — `gd_integration_tools`.
> Этот файл читается ОБОИМИ агентами при старте сессии.
> Создан для унификации контекста и команд между Claude Code и Kimi Code.

---

## Сначала прочти (в этом порядке)

1. **`PLAN.md`** (V22) — текущий roadmap, архитектурные решения, **источник правды**
2. **`vault/SESSIONS.md`** — последние 5–10 сессий (append-only лог, Ivan-локальный)
3. **`vault/DECISIONS-LIVE.md`** — открытые решения, ожидающие review
4. **`ARCHITECTURE.md`** — слои и их границы (frontend → entrypoints → services → core → infrastructure → dsl)
5. **`.claude/DECISIONS.md`** — закрытые архитектурные решения (snapshot)
6. **`.claude/KNOWN_ISSUES.md`** — известные проблемы
7. **`graphify-out/`** — индекс кода (если есть) — `graphify query <sym>` для навигации

> **Не читай весь репозиторий без необходимости.** Связи — через `graphify query/path/explain`
> или `codebase-map` skill.

---

## Контекст проекта (краткая сводка)

**`gd_integration_tools`** — универсальное domain-agnostic ядро интеграционной шины
на Python 3.14+ (Apache-Camel + Airflow style). Внутренний продукт банка.

**Ключевые возможности:**
- DSL: YAML + Python builder (Camel-style fluent)
- Workflow / orchestration: Temporal (default) + LiteTemporalBackend (dev_light)
- Multi-protocol auto-registration: REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT
- Multi-backend gateways: PG↔Oracle↔MSSQL↔MySQL↔DB2; Redis↔KeyDB; S3↔MinIO↔LocalFS; Kafka↔RabbitMQ↔NATS
- RPA, CDC, file-watcher, webhook source/sink
- AI/RAG/agents с MCP-сервером (FastMCP) + AI Safety (workspace isolation)
- Multi-tenancy (TenantContext + per-tenant SLO/quotas)
- Developer portal на Streamlit (36+ страниц)

**Бизнес-логика** — только в `extensions/<name>/`. Ядро domain-agnostic.
**80% декларативно (YAML/TOML) / 20% Python.**

**Капитальные элементы V22:** BasePlugin + PluginLoader, RouteBuilder, WorkflowBuilder,
ActionDispatcher, ProcessorRegistry, Schema-registry, ResilienceCoordinator,
ServiceDSLRegistry, AIToolAdapter + AIWorkspaceManager.

**Слои:**
```
frontend/streamlit_app/  ─►  src/entrypoints/  ─►  src/services/  ─►  src/core/  ─►  src/infrastructure/  ─►  src/dsl/
                          (REST/SOAP/gRPC/      (core, ai, intgr,    (Protocols,  (db, cache, storage,    (route, workflow,
                           GraphQL/WS/SSE/      ops, execution,      interfaces,  messaging, search,      service, contracts,
                           MQTT/MCP/CDC)        plugins)             di, tenancy) audit, sources, ...)    engine, blueprints)
```

---

## Команды (основные)

### Sync-команды (regenerate auto-generated configs)
| Команда | Назначение |
|---------|-----------|
| `make sync-agents` | Проверить `.shared/` + `vault/` на месте |
| `make sync-mcp` | Recreate `.mcp.json` + `.kimi-code/mcp.json` symlinks из `.shared/mcp-servers.json` |
| `make sync-mcp-verify` | Drift check: symlinks корректны, нет hardcoded secrets |
| `make sync-permissions` | Regenerate `.claude/settings.json` + `.kimi-code/config.toml` из `.shared/permissions.yaml` |
| `make verify-permissions` | Drift check: оба файла совпадают с YAML |
| `make session-start AGENT=<claude\|kimi> MSG="..."` | Append-only запись в `vault/SESSIONS.md` (фаза 4) |
| `make session-close` | Закрыть запись в `vault/SESSIONS.md` (фаза 4) |

### Quality-команды
| Команда | Назначение |
|---------|-----------|
| `make format` / `make lint` / `make type-check` | Ruff format / soft lint / mypy non-blocking |
| `make test` | pytest |
| `make ci` | composite gate (lint + type + tests + security + WAF strict) |
| `make audit` | security + dependency audit |

### Graphify
- `source .shared/context/graphify-aliases.sh` — загружает shell-функции
- `gq "<question>"` — `graphify query` (BFS traversal, рекомендуемый)
- `gp "A" "B"` — `graphify path` (shortest path)
- `gx "X"` — `graphify explain` (plain-language)
- `gu .` — `graphify update` (re-extract, pre-commit hook)
- `ge .` — `graphify extract` (headless AST + LLM)
- `gs` — graphify status (binary, graph.json, contents)
- `gh-install` / `gh-uninstall` / `gh-status` — git hooks management

---

## Правила работы

### Категорически запрещено
- Читать `.env`, `.env.*`, `secrets/**`, `*.pem`, `*.key`, `*secret*`, `*token*` (закреплено в permission rules обоих агентов)
- `git push`, `make push`, `make ship`, `make ship-release`, `make clean-all`, `rm -rf`, `pip install`, `poetry add`, `poetry remove` — всё под deny
- Импорт `extensions/*` → `infrastructure/*` / `services/*` напрямую
- Бизнес-логика вне `extensions/<name>/`
- Изменения в lock-файлах без явного согласования (Sprint 36)
- Force-push, reset --hard, чистые merge-коммиты
- Secrets в коде, логах, коммитах (только через Vault / `${ENV_VAR}`)
- PII в логах (`detect-secrets` в CI)

### Обязательно
- **Type hints везде** (Python 3.14+ синтаксис: `int | str`, generic `class Foo[T]`)
- **Async-first** (FastAPI/Temporal). Никаких blocking I/O в async-контексте
- **Pydantic** модели для DTO/схем (`BaseModel`, `ConfigDict`, `Field`)
- **Тесты pytest** с markers (`@pytest.mark.unit`, `.integration`, `.asyncio`)
- `make lint && make type-check && make test` перед коммитом
- `make format` (ruff) перед коммитом
- Capability-checked фасады для cross-layer доступа
- `graphify update .` после структурных изменений (через pre-commit hook)
- **Commit короткий, Russian-first, без emoji**
- **Conventional prefix в коммите:** `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `perf:`
- **Атомарные коммиты** (одна логическая правка = один коммит)
- **`--no-verify`** при коммите (graphify pre-commit hook ~60s delay; CI ловит drift)

### Рекомендуется
- 80% декларативно (DSL) / 20% Python
- Изучить существующий паттерн перед добавлением нового модуля
- План → стоп → ревью → согласование → следующий шаг
- Финал работы — список задач (НЕ выдуманные улучшения)

### Стиль ответов
- **Russian first, English second**
- Кратко, по делу, без воды
- Варианты A/B/C/D вместо открытых вопросов
- Без emoji в технических ответах без явной просьбы
- Markdown только по делу

---

## Vault (Ivan-локальный workspace)

- `vault/SESSIONS.md` — append-only лог сессий (gitignored, Ivan'а)
- `vault/DECISIONS-LIVE.md` — открытые решения, ожидающие review (gitignored)
- `vault/knowledge/` — заметки обоих агентов (gitignored, `YYYY-MM-DD-<agent>-<slug>.md`)
- `vault/INDEX.md` — указатель на артефакты (генерируется `make vault-index`, фаза 4)

**Read permissions** для `vault/` уже выданы обоим агентам через `.shared/permissions.yaml`:
- `Read(./vault/SESSIONS.md)` — да
- `Read(./vault/DECISIONS-LIVE.md)` — да
- `Read(./vault/knowledge/**)` — да
- `Read(./vault/INDEX.md)` — да
- `Read(./vault/**)` — ask (запись с подтверждением)

---

## Skills (slash-команды для обоих агентов)

Kimi Code автоматически подхватывает из `.claude/skills/` (через `extra_skill_dirs`):
- `codebase-map` — навигация по коду
- `plan-execute` — выполнение плана
- `verify-change` — pre-commit verification
- `compact-session` — сжатие контекста
- `connector-building` — коннекторы
- `refactoring` — рефакторинг
- `workflow-engineering` — Temporal workflow
- `feature-development` — фичи
- `commit-work` — коммиты
- `research-current-tech` — research

Из `.kimi-code/skills/`:
- `python-dev` — правила Python-разработки
- `code-review` — чеклист ревью

**Формат вызова:** `/skill:<name> [аргументы]`

---

## Если что-то непонятно

1. **Сначала** проверь `PLAN.md` (V22) — там архитектурные решения
2. **Потом** проверь `.claude/DECISIONS.md` — почему было решено именно так
3. **Потом** проверь `.claude/KNOWN_ISSUES.md` — может это уже известный баг
4. **Потом** спроси Ivan'а (НЕ угадывай)

> **Финал работы — список задач, НЕ выдуманные улучшения.**
> Если непонятно — задай 3-4 уточняющих вопроса, не генерируй 1000 слов.
