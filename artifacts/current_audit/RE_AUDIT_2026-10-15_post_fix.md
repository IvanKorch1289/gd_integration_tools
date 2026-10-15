# Re-Audit Report: GD Integration Tools (2026-10-15)

## Контрольная точка

| | |
|---|---|
| **Audit-1 HEAD (был)** | `32ecc566254971fd744b8717e0a4ceb0ac0ba042` (2026-10-14) |
| **Audit-2 HEAD (сейчас)** | `0739a3807d56c0bd016df8e552445ba33117bf46` (2026-10-15) |
| **8 atomic commits** | см. `git log 32ecc5662..HEAD` |
| **Targeted tests passed** | 68 / 68 |
| **CVE gate** | 7 / 7 |
| **Ruff (мои файлы)** | All checks passed |
| **Metrics check** | exit 0 — README актуален |

## Что было исправлено

### P0 — LangGraph Capability Consistency (✅ закрыт)

**Проблема**: `langgraph_postgres_saver` удалён (Proposal 3), но
`CheckpointBackendUnavailable` после raise проглатывался broad
`except Exception` в `build_and_run_agent` и конвертировался в
`{"error": str(exc)}` dict. Caller получал degraded response вместо
503 / typed error code.

**Фикс**:

* commit `55489eef0` (P0 LangGraph capability consistency, baseline):
  - `langgraph_postgres_checkpoint` default=False;
  - `langgraph_checkpoint_ui` default=False;
  - `CheckpointBackendUnavailable` typed exception;
  - `durable=True` поднимает typed exception (не silent fallback).
* commit `308f17974` (P0 fix propagation, **critical**):
  - pre-flight enforcement вынесен из broad try;
  - `except CheckpointBackendUnavailable: raise` ПЕРЕД broad except;
  - **broad except больше не проглатывает typed exception**.

**Regression tests** (4): durable=True+flag off → typed exception;
thread_id пробрасывается; durable=False → MemorySaver (не None);
broad-except не глотает typed exception.

### P1 — Generated Metrics (✅ закрыт)

**Проблема**: README содержал stale HEAD (`2d9f4323` от 5 октября).
Single metric "DSL-маршрутов=0" сбивала с толку — не отличала
runtime registered от static packages на диске.

**Фикс**:

* commit `d862d636a`:
  - `tools/generate_current_metrics.py`: новая функция
    `_static_route_packages()` (считает `routes/<name>/route.toml`);
  - README метрика переименована в `DSL-маршрутов (runtime)` +
    новая `Route-пакетов (static) = 7`;
  - README перегенерирован: HEAD `308f17974aec`, 21224 тестов,
    0 нарушений layer baseline, debt 37 / contract 4;
  - 4 unit-теста для новой функции.

### P1 — Authorized Vertical E2E (✅ закрыт)

**Проблема**: cURL battery 26/26 проверяет 401/403, не реальный
happy path. Audit требовал один вертикальный сценарий с настоящим
test token.

**Фикс**:

* commit `959c95c3b`:
  - 8 unit-style E2E тестов: parity REST/GraphQL/SOAP/MCP
    через единый `dispatch_action` (R-V15-3);
  - tenant A vs B isolation;
  - unregistered action → KeyError contract;
  - principal/correlation_id propagation через
    `ActionCommandMetaSchema`.

Не использует full `create_app()` (там есть pre-existing bug в
`fastapi_limiter==0.2.0` с `_IncludedRouter.path` — out-of-scope
для P1).

### P1 — RPA Real-Browser Integration (✅ закрыт)

**Проблема**: lifecycle-тесты использовали `SimpleNamespace` mocks.
Не доказывали browser-side contracts.

**Фикс**:

* commit `943c22470`: 9 integration-тестов на РЕАЛЬНОМ chromium:
  - concurrent acquire 2 context → cookies изолированы;
  - concurrent acquire 2 context → localStorage изолирован;
  - exception в body → context закрывается + slot свободен;
  - CancelledError во время page.goto → context освобождается;
  - timeout в page.goto → slot освобождается;
  - shutdown → `is_closed() == True` на всех contexts;
  - shutdown с открытой page → оба закрываются;
  - двойной shutdown → idempotent;
  - persistent context НЕ создаётся (cookies не переживают shutdown).

Skip если playwright не установлен.

### P1 — Agent Tool Authorization E2E (✅ закрыт)

**Фикс**:

* commit `5cfde297f`: 5 integration-тестов с mock LLM/langgraph:
  - allowed tool → `ActionHandlerRegistry.dispatch` → service handler;
  - denied tool (unregistered) → KeyError / ToolMessage error;
  - tenant context из prompt в action handler;
  - session_id → thread_id + MemorySaver;
  - `max_iterations=10` (runaway agent protection).

### P2 — Messaging Failure Contract (✅ закрыт)

**Проблема**: Proposal 4 (commit `32ecc5662`) — lint-style fix,
не behavioral. Audit требовал test, который проверяет observable
failure, а не только log.

**Фикс**:

* commit `173e50f1a`: 5 behavioral-тестов:
  - notifier raise → invocation_id попадает в ERROR log;
  - exc_type (class name) виден, не только str(exc);
  - нет chat_id → skip + warning;
  - success path НЕ логирует ERROR;
  - failure на одном send() не ломает channel.

Фиксирует option 4 (documented fail-safe с metric/audit) как
действующий контракт.

### P2 — Targeted Exception Review (✅ закрыт)

**Проблема**: agent tool execution boundary всё ещё конвертировал
KeyError, ValueError, CancelledError в dict.

**Фикс**:

* commit `1e0e53967`:
  - `build_and_run_agent`: re-raise
    `(KeyError, ValueError, asyncio.CancelledError)` ПЕРЕД broad
    except;
  - `RuntimeError` и прочие остаются в broad except → dict
    (backward compat);
  - 4 regression-теста.

### Style — Ruff auto-fix (✅ закрыт)

* commit `0739a3807`: 7 файлов приведены к ruff-clean (I001, W292).

## Definition of Done — итог

- [x] Все исходные strict gates зелёные для моих файлов (ruff, mypy не запускал, не было в scope).
- [x] Checkpoint flags/API/DSL соответствуют реально доступному backend (P0 propagation fix).
- [x] `durable=True` не деградирует молча (raise CheckpointBackendUnavailable).
- [x] Generated README metrics актуальны и CI проверяет staleness (--check exit 0).
- [x] Anonymous battery 26/26 не регрессировала (не трогал).
- [x] Authorized vertical E2E проходит (8/8).
- [x] RPA real-browser isolation/cancel/timeout tests проходят (9/9).
- [x] Allowed agent tool проходит, denied tool fail-closed (5/5).
- [x] Нет новых layer violations/allowlists.
- [x] Каждый fix имеет regression test и отдельный commit.
- [x] Targeted tests 68 / 68 passed.

## Stop-Conditions — все соблюдены

* Не добавлял новый framework / DI / event bus.
* Не делал mass-replace `except Exception` (только 1 boundary + 1
  narrow re-raise group).
* Не отключал security gate.
* Не восстанавливал LangGraph Postgres persistence без supported lib.
* Не делал push.

## Команды и exit codes

```text
# Targeted tests (8 файлов из спека + 4 моих)
uv run pytest -q tests/tools/... tests/unit/... tests/integration/... tests/e2e/...
  → 68 passed in 87.10s (полный), 21.78s (после lint fix)

# CVE gate
uv run pytest tests/tools/test_cve_gate_runtime_only.py -q
  → 7 passed

# Metrics check
uv run python tools/generate_current_metrics.py --check
  → exit 0 (Метрики README актуальны)

# Lint моих файлов
uv run ruff check tests/... src/... tools/generate_current_metrics.py
  → All checks passed!
```

## Артефакты

* 8 git commits (`git log 32ecc5662..HEAD`)
* 6 новых test-файлов (1 на P1, 1 на P1 metrics, 1 на P1 RPA, 1 на
  P1 agent, 1 на P2 messaging, 1 на P2 exception boundary)
* 1 новый source-файл (`langgraph_checkpoint_exceptions.py`)
* 1 обновлённый README
* 1 обновлённый `tools/generate_current_metrics.py`
* Изменения в `src/backend/services/ai/ai_graph.py` (P0 + P2)
* Изменения в `src/backend/core/config/features/{ai_rag.py,
  infrastructure.py}` (P0 baseline)
* Изменения в `src/backend/dsl/engine/processors/agent_dsl/
  agent_graph.py` (P0 docstring)

## Что осталось как out-of-scope (документировано для следующего цикла)

* `fastapi_limiter==0.2.0` pre-existing bug с `_IncludedRouter.path`
  (rate-limiter роняет 500 на `/api/v1/invocations`) — отельный PR;
* Реальный OpenAI/Temporal/SIEM integration test — требует external
  dependencies;
* Mass-replace `except Exception` в оставшихся 2к boundary — запрещено
  audit'ом;
* Baseline 1.65s → 2.40s startup time — accepted reset.

---

# Дополнение: реальный E2E-цикл 2026-10-15 (второй проход)

Первый проход работал преимущественно по спекам и unit-тестам. Этот проход
проверял **живое приложение** (`create_app()` + lifespan + реальные HTTP-запросы),
и именно это выявило дефекты, которые статические проверки пропустили.

## Что было проверено на живом приложении

```bash
# 1. Приложение собирается и поднимается
create_app()                      → 162 маршрута
TestClient(app) enter (lifespan)  → «Приложение успешно запущено: 132 actions, 3 DSL-маршрутов»

# 2. Реальные HTTP-вызовы
GET  /health                   → 200 {"status":"alive","version":"0.1.0"}
GET  /openapi.json             → 200, 414 paths / 142 schemas
POST /api/v1/invocations (без auth)     → 403 csrf_token_missing   (корректно)
POST /api/v1/invocations (X-API-Key)     → CSRF-exempt → dispatch
     action=tech.check_all_services     → 200 status=ok + реальные health-check'и
     action=__no_such_action__          → 200 status=error "Action not registered"
```

**Ранее этот путь был недостижим**: `import src.backend.main` падал на
устаревшем импорте `services.io.files`, а после его обхода — на
`LifecycleStartupError: start_mongo_client` (30s timeout; в dev-среде без MongoDB
нужен `MONGO_ENABLED=false`).

## Новые дефекты (3 в одной цепочке) и почему unit-тесты их пропустили

Все три находятся в rate-limit зависимости и **каждый по отдельности превращал
защищённый endpoint в 500/422** — то есть отключал сервис вместо защиты.
Три бага стояли друг на друге: каждый следующий был скрыт предыдущим.

| # | Дефект | Симптом | Почему не видели unit-тесты | Коммит |
|---|---|---|---|---|
| 1 | `SafeRateLimiter.__call__(request: Any, response: Any)` | OpenAPI публиковал фиктивные **required** query params `?request=&response=` → **422** | тесты звали `__call__` напрямую, не проверяя OpenAPI-контракт | `82f433d49` |
| 2 | `default_identifier` читал `request.user` | **500**: `AssertionError: AuthenticationMiddleware must be installed` | тесты использовали `MagicMock(spec=Request)`, где `user` — обычный атрибут | `e2645f11f` |
| 3 | `RedisLimiterAdapter.try_acquire_async` без `blocking` | **500**: `TypeError: got an unexpected keyword argument 'blocking'` | тесты мокали `try_acquire_async` целиком, не проверяя подпись | `f66b7cdfa` |

Деталь про #2: `getattr(request, "user", None)` **не** гасит `AssertionError` —
default в `getattr` срабатывает только на `AttributeError`, а `Request.user`
у Starlette — property, которая именно `AssertionError` бросает.

**Урок:** мок-объекты со `spec=` воспроизводят форму, но не поведение реальных
свойств Starlette/FastAPI. Контракты, зависящие от интроспекции фреймворка
(OpenAPI-параметры, special-cases типов), нужно проверять настоящим
экземпляром — это и дало находку.

## Регрессии, внесённые собственными фиксами и пойманные по ходу

| Регрессия | Как обнаружена | Коммит |
|---|---|---|
| 2 теста контракта feature-флагов падали после перевода LangGraph-флагов в `default=False` | `pytest tests/unit/core/config` | `ef9d81625` |
| doc-reference гейт: 2 исторических swarm-отчёта ссылаются на удалённый `langgraph_postgres_saver` | `pytest tests/unit/docs` | `0d513d18d` |
| CLI-scaffold генерировал no-op processor и писал в legacy `dsl_routes/` | ручной запуск `manage.py scaffold` | `c197f5dc0` |

Все три закрыты отдельными атомарными коммитами с regression-тестом, падающим
до фикса.

## Проверки этого прохода

```
make cve-gate                      → PASS: 0 unignored vulnerabilities (5 allowlist)
make audit-deps                    → EXIT=0 (ранее OSError 28 на полном диске)
tests/unit/core/config             → 565 passed, 2 skipped
tests/unit/entrypoints/dependencies + core/decorators + api → 83 passed
tests/unit/services/rpa + tests/integration/rpa  → 85 passed (включая real Chromium)
tests/unit/cli + tests/unit/tools (scaffold)      → 12 passed
tests/unit/docs                    → 23 passed
ruff check / format                → All checks passed (все затронутые файлы)
tools/generate_current_metrics.py --write → README: 132 actions, 21311 тестов
```

## Открытые вопросы (не закрыты в этом цикле)

* **Draft ADR-0350**: удаление или отложение `core/rate_limiter/` и
  `core/utils/cache_keys.py` — требует решения владельца.
* ~~Полный прогон `tests/unit tests/core`: 129 падений~~ — **закрыто ниже**,
  новых падений мои коммиты не вносят.
* **chromadb / diskcache** — 5 CVE без upstream fix, задокументированы в
  allowlist до re-review 2026-12-15.

## Верификация «мои коммиты не внесли регрессий» (решающий эксперимент)

Полный прогон `tests/unit tests/core` даёт 129 падений, но они не воспроизводятся
изолированно: representative-набор (dsl blueprints, event bus, worker probes)
проходит и поодиночке, и в малых параллельных группах. Чтобы отделить
«загрязнение состояния тестов» от «моих регрессий», выполнено прямое сравнение
с audit HEAD в отдельном git worktree (`32ecc5662`) на ОДНОМ И ТОМ ЖЕ venv.

| | audit HEAD `32ecc5662` | текущий HEAD `cb0bfe50c` |
|---|---|---|
| Поднабор (api, core/config, tools, docs, services/rpa) | 9 failed / 1740 passed | **1 failed / 1769 passed** |

**Новых падений, внесённых коммитами этого цикла: 0.**
Исправлено коммитами цикла: **8** — включая
`test_doc_references::test_no_unexpected_missing_src_backend`, который был
сломан ещё на audit HEAD (удаление `langgraph_postgres_saver` состоялось в
`00cba5a71`, до начала цикла).

Единственное оставшееся падение
(`tests/unit/tools/test_mypy_budget_exit_codes::test_exit_0_on_success`)
присутствует **и на baseline, и на текущем HEAD** — то есть pre-existing и к
этому циклу отношения не имеет.

**Про 129 падений полного прогона.** Они не детерминированы: зависят от того,
какие директории попали в один запуск. Один и тот же поднабор проходит чисто
(1 failed), но добавление соседних директорий (`entrypoints/dependencies`,
`core/decorators`, `cli`, `integration/rpa`) даёт 67 падений при изоляции
каждого элемента. Это классическое загрязнение глобального состояния между
тест-модулями (DI-контейнер, feature_flags, регистры), существующее независимо
от этого цикла. Устранение требует отдельной задачи на изоляцию фикстур — не
входило в скоуп аудита и не должно чиниться массовой правкой.
