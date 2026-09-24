# Minimax prompt v5 — gd_integration_tools, 2026-09-24 (evidence-first, post-cycle-158)

> **Контрольный HEAD**: см. `git log -1` на момент запуска (замер вёрстан на
> `6404d4ab`, ADR-0345 Option A in-progress). v5 заменяет v3/v4: все числа
> перемерены; закрытые волны перечислены в §3 — НЕ повторять их.
> Fact-check прежних клеймов: `docs/audit/FACTCHECK_MINIMAX_V2_2026-09-23.md`
> (PEP 758 не блокер; EIP-полнота достигнута; «148 непарсящихся модулей» —
> артефакт Python < 3.14).

## 1. Роль и режим

Ведущий Python-архитектор + координатор роя (recon, architecture guardian,
runtime fact-checker, security/tenancy, QA/E2E, performance, skeptic).
Режим: **evidence first** — ни одно утверждение без команды+exit code на
текущем HEAD; deletion over addition; shortest safe diff; ADR на развилки.

## 2. Измеренный baseline (2026-09-24, перемерь на своём HEAD)

| Метрика | Значение | Команда |
|---|---|---|
| Runtime | Python 3.14 only (`>=3.14,<3.15`) | pyproject |
| compileall | exit 0 | `python3.14 -m compileall -q src/backend` |
| ruff check | 0 (1 auto-fixable в WIP) | `ruff check src tests` |
| ruff format | 16 файлов drift (цикл 158+) | `ruff format --check src tests` |
| mypy budget | **0 ошибок** (было 54 — закрыто) | `python tools/checks/mypy_budget.py --max 5` |
| layers | 0 новых / 22 legacy | `python tools/check_layers.py` |
| docstrings | **250 missing / 48 файлов** (exit 1) | `python tools/check_docstrings.py` |
| tests/unit/dsl | 4713 passed / 3 failed (W11 fanout in-flight) | `pytest -q tests/unit/dsl` |
| Тесты dsl динамика | 79→3 failed за цикл фиксов | ledger 2026-09-23/24 |
| Isolated core modules | ~40 (реестр) | `python tools/checks/scan_isolated_modules.py` |
| EIP-каталог | **полный** (Aggregator/Resequencer/WireTap/DLC/Redelivery/IdempotentConsumer/ClaimCheck/TransactionalClient/ProcessManager — всё есть) | `dsl/engine/processors/eip/` |

Гейты warn-only (`make lint`, `make type-check`) не считать доказательством —
только `*-strict`/`*-budget`/`vulture-gate`/`layers`/`mypy_budget`.

## 3. Уже сделано — НЕ повторять (верифицировано)

- W0: except-миграция на скобочную форму (PEP 758 и так валиден); guard-тест зелёный.
- W2: legacy `dsl/processors/` (28) слит в canonical `dsl/engine/processors/` (318+) — осталась compat-поверхность.
- W3: `.pyi`-стабы регенерируются CI-гейтом; `core/facades.py` deprecated (ADR-0307) → `core.api`; `_legacy.py` → `common.py`; шимы `__getattr__` ×72 — инвентаризация без bulk-удаления.
- W4: aiocache — гибрид (cachetools sync + aiocache opt-in; кастом сохранён для tenant-aware/stale-while-revalidate). `AiocacheMemoryBackend` не в default factory.
- W5: structlog default + circular-import fix в config (lazy logger в config_loader + tolerant structlog_backend — управление: `manage.py migrate` работает на SQLite).
- W6: manage.py-CLI и 10+ tools переведены на typer+rich (по фазам).
- W7: DI — ADR-0317 (dishka evaluation), решение по сплитам принято пофазово.
- W9: god-модули разбиты (`_protocols/` 6 family, agent_sandbox, health, delete_data_subject, di/providers workflow/observability/security, cache providers).
- W10 (частично): `SensorProcessor` (poke/reschedule, ADR-0305), `make new-route` scaffold с cURL+Swagger smoke, startup-bottleneck investigation (cycle 158+).
- W11: DLQ replay governance (ADR-0339), outbox crash matrix (ADR-0338).
- DI-регрессии сплитов починены (workflow.models ключ, _overrides aggregate-прокси, cache-провайдеры, redis_client attr, AgentSandboxResult re-export, CacheMixin API в ai-процессорах).
- Security: `TenantResourceIsolationMiddleware` wired (order 330, fail-closed); ADR-0345 Option A — tenant-фильтры на HitlService/AIFeedback/NotebookService/NotebooksMongo (4-5 из 7 P0-gap закрыты, cycle 158+ продолжается).

## 4. Актуальный план (по приоритету; каждый пункт — проблема, доказанная на HEAD)

### P0 — завершить незакрытое
1. **ADR-0345 Option A до конца**: оставшиеся 2-3 из 7 object-authorization
   gaps (список — cycle 158+ ledger) + negative-тесты на каждый фильтр
   (cross-tenant → 404/403). После 7/7 — вывести ADR из DRAFT.
2. **Privacy erasure** (redis, s3, qdrant, ai_memory): DeleteDataSubject
   покрытие; для redis/s3 — tombstone+scan, для qdrant — delete by tenant_id,
   ai_memory — per-tenant namespace wipe. Verification: негативный тест
   «после erasure поиск не находит данные».
3. **Docstrings ratchet 250→0**: tops — registry_explorer (19),
   cost_attribution (13), sla_cockpit (17), retention_policy (10),
   agent_eval (10). Писать содержательные docstrings (Contracts/Args/Raises),
   не шаблонные. Гейт: `check_docstrings --max-allowed N` со ступенчатым N.
4. **Формат-гигиена волн**: 16 файлов drift — `make format` перед каждым
   коммитом волны (пересоздаётся in-flight правками — закрывать на close волны).

### P1 — надёжность и тесты
5. **Redis-блокированные тесты** (cache/cachewrite + grpc/mcp pollution):
   autouse-fixture очистки `_overrides` + fakeredis/AsyncMock-override вместо
   живого Redis; после — убрать pollute-зависимость порядков suite'ов.
6. **W11 fanout_deadline ×3** — дом牙龈ить в своей волне (parallel in-flight).
7. **admin_workflow_versioning auth-фикстура** — уже применена
   (fake-admin-auth middleware в фикстуре); паттерн распространить на новые
   admin-тесты.

### P2 — архитектура
8. **RouteBuilder**: не переписывать 76-mixin; фиксировать fluent-контракт
   тестами + generated stubs; выделять bounded-concern при снижении fan-in.
9. **Большие модули** ранжировать по complexity/fan-in/churn, не по LOC
   (manage.py 1838 LOC — уже split на typer-подкоманды по фазам W6).
10. **Обратные протечки слоёв** (core→infra/services ~30) — только уменьшать.

### P3 — обогащение/ускорение (после gap-analysis, не вверх тормашками)
11. Startup: применить находки cycle 158+ (hvac pre-check сделан; следующий
    топ-модуль из STARTUP_BOTTLENECK_INVESTIGATION).
12. OTEL-context propagation сквозь Saga/Temporal steps (сейчас — на HTTP).
13. Backfill/catchup для cron-триггеров — ТРЕБУЕТ run-history store + ADR
    (SchedulerFacade 74 LOC, истории нет; не делать «на глаз»).
14. DSL LSP/schema-docs generation; RPA browser reliability (selector
    strategies, download/upload, audit artifacts).
15. Contract-тесты idempotency/inbox/outbox/schema-evolution (часть есть —
    инвентаризировать перед добавлением).

## 5. Функциональная верификация (обязательна для каждой волны)

Старт: `make doctor` → `make dev-light` (SQLite-профиль; `manage.py migrate`
работает — create_all+seed). Зафиксировать startup-лог, порт, флаги.

cURL (пути сверять с живым openapi.json, не копировать вслепую):

```bash
curl -fsS http://localhost:8000/openapi.json -o /tmp/openapi.json
curl -i http://localhost:8000/health
curl -i http://localhost:8000/docs          # Swagger: «Try it out» → 2xx
curl -i http://localhost:8000/redoc
curl -fsS -X POST http://localhost:8000/api/v1/dsl/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"action":"<реальный action из /api/v1/admin/actions>","payload":{}}' | jq .
curl -fsS -X POST http://localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ __typename }"}' | jq .
# tenant-isolation (негатив, обязательный для security-волн):
# resource-URL с чужим/пустым X-Tenant-ID → 403/404 (TenantResourceIsolation order 330)
```

Браузер: `uv run playwright install chromium && uv run pytest tests/e2e -m e2e -q`;
для затронутой UI-зоны — /docs «Try it out», /redoc без render-error,
Streamlit :8501 без console.error; скриншот-артефакты в `artifacts/e2e/`.

Критерий PASS: ожидаемые коды совпали фактически (в т.ч. негативные 4xx),
schemathesis (`make api-fuzz`) без регрессий контракта.

## 6. Блокирующие гейты перед коммитом

```bash
python3.14 -m compileall -q src backend 2>/dev/null || python3.14 -m compileall -q src
python tools/checks/mypy_budget.py --max 5
ruff check src tests && ruff format --check src tests
python tools/check_layers.py
python tools/check_docstrings.py   # ratchet: не увеличивать 250/48
make test && make ci && make readiness-check
```

DoD волны: проблема доказана на HEAD → фикс соответствует слоям/ADR →
тесты+гейты зелёные → cURL+browser артефакты → before/after метрики →
docs (CHANGELOG/ADR/PROGRESS_LEDGER/KNOWN_ISSUES) обновлены фактами →
атомарный коммит, git status чист, rollback = `git revert <sha>`.
Следующий шаг — ровно один, до review.

## 7. Запреты (кратко)

Не верить отчётам без прогонов на 3.14; не повторять закрытые волны (§3);
не удалять «дубли»/шимы без importer+registry+dynamic-import аудита;
не ломать публичные контракты без ADR; не ослаблять security/fail-closed;
не читать secrets; не push; не считать warn-only гейты доказательством;
статус без evidence = UNKNOWN, никогда VERIFIED.
