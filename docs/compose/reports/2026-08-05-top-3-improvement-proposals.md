# Top-3 Improvement Proposals — S36 P0-close retrospective

> **Дата**: 2026-08-05
> **Контекст**: 5 P0-фиксов закрыты multi-agent аудитом (см. `2026-08-05-multi-agent-domain-audit.md`).
> Branch: `s36-p0-fixes` @ `f57c54b8`
> **Автор**: analyst subagent (general-13), свежий контекст без предыдущих сессий.

## TL;DR

| # | Proposal | Type | LOC Δ | Effort | Risk | Score (lib/fit) |
|---|---|---|---|---|---|---|
| 1 | ClickHouse DLQ unification через tenacity+purgatory | library_replacement | -50% | M | 7 | 9/10 |
| 2 | idempotency middleware → asgi-idempotency-header RedisBackend | library_replacement | -60% | S | 8 | 8/10 |
| 3 | per-tenant SLO-budget preflight в Temporal workflows | new_capability | +0% (net add) | M | 5 | N/A / 10 |

Все 3 утверждены пользователем через `question` tool 2026-08-05.

---

## Proposal #1: Replace custom ClickHouse retry-loop + JSONL DLQ с `tenacity` AsyncRetrying + `purgatory.backends.disk`

### Type
**library_replacement**

### Library
- `tenacity>=9.0` (уже в deps, line 74 pyproject.toml)
- `purgatory>=3.0` (уже в deps, line 53)

### Evidence (post f57c54b8)
`src/backend/services/audit/clickhouse_audit_service/service.py:90-223` — содержит ~70 LOC ручного DLQ-write loop поверх `JsonlAuditBackend` с собственным форматом ошибок и metadata-полями.

T1 commit (44e64c15) закрыл silent-loss, но оставил фрагментированный retry:
- `@resilient(name=…, max_attempts=3)` декоратор уже используется в других ClickHouse-путях
- `emit/emit_batch` используют отдельный ручной цикл через `retry_async` + `_send_to_dlq`
- JSONL-формат DLQ-файла (lines 160-180) дублирует контракт `purgatory.backends.disk.DiskBackend`

### Estimated impact
- **LOC reduction**: ~50% в `clickhouse_audit_service/service.py` (388→~195 LOC, ~-193 LOC)
- **Capability gain**: единый retry/DLQ contract для всех audit-бэкендов (ClickHouse → Kafka → S3 → PG) — закрывает P1-3 «audit emit consistency» из бэклога multi-agent аудита
- **Effort**: M (1-2 sprint-days; требуется согласование с `core/facades.py` для retry-helper extension)
- **Risk**: 7 (изменение контракта `ClickHouseAuditService` — внешние extensions могут зависеть от JSONL-формата; нужен backward-compat shim с deprecation warning)

### Scores
- Library match: **9/10** (tenacity — LTS-grade, уже 2 года в стеке; purgatory — internal, но disk-DLQ его каноническая функция)
- Fit with philosophy: **10/10** (Ponytail: «reuse existing lib»; multi-tenant audit emit становится единым для всех бэкендов)

### Why now
T1 (44e64c15) закрыл silent-loss в ClickHouse, но оставил фрагментированный retry. P1-3 в бэклоге (audit emit consistency across backends) прямо закрывается.

### Concerns / mitigations
- **backward-compat**: с существующими JSONL-файлами в проде; требуется migration-флаг `clickhouse_legacy_dlq_path` для чтения старых записей в течение 30 дней
- Purgatory — internal lib (стабильный), но не external-dep — при внесении изменений в purgatory нужно синхронизировать

---

## Proposal #2: Standardize idempotency middleware на `asgi-idempotency-header` (уже в deps) — убрать кастомный `RedisNxBackend`

### Type
**library_replacement**

### Library
- `asgi-idempotency-header` (already installed: `asgi-idempotency-header>=0.2.0,<1.0.0`, line 38 pyproject.toml)

### Evidence (post f57c54b8)
`src/backend/entrypoints/middlewares/idempotency.py:40-131` — класс `RedisNxBackend` (91 LOC) реализует 4 метода (`get_stored_response`, `store_response`, `store_idempotency_key`, `clear_idempotency_key`) поверх `redis.asyncio` с NX-блоком.

Сам файл **уже импортирует**:
- `from idempotency_header_middleware.backends.base import Backend` (line 22)
- `MemoryBackend` (line 23)

…но реализует кастомный Redis backend вместо использования штатного `idempotency_header_middleware.backends.redis.RedisBackend`.

### Estimated impact
- **LOC reduction**: ~60% в `idempotency.py` (180→75 LOC, ~-105 LOC)
- дополнительно ~-20 LOC в `build_idempotency_backend` через использование фабрики из библиотеки
- **Capability gain**: получаем бесплатно:
  - TTL-rotation
  - header re-validation
  - `Idempotency-Replayed: true` response header (отсутствует в текущей реализации)
- **Effort**: S (полдня; one-shot миграция с тестами)
- **Risk**: 8 (нужно проверить, что RedisBackend из lib использует тот же префикс `idem:pending:` — иначе миграция ломает in-flight idempotency keys)

### Scores
- Library match: **8/10** (lib LTS-grade, используется уже в проекте через base-class import — низкий риск незрелости)
- Fit with philosophy: **10/10** (Ponytail: «replace custom code with mature library»; multi-protocol consistency — middleware уже используется и для REST, и для Webhook relay)

### Why now
M5 Middleware audit (commit 60f96f9) централизовал 30+ middleware, но idempotency остался полу-кастомным. T2 (layer-violation fix 8b68f8a3) не затронул middleware-слой — логичное продолжение M5.

### Concerns / mitigations
- Проверить, что `asgi-idempotency-header` совместим с `httpx`-based тестами (текущий код тестируется с `MemoryBackend`)
- Один minor breaking-change в response-header формате может потребовать обновления `webhook_relay` тестов

---

## Proposal #3: Per-tenant SLO-budget preflight в Temporal workflow (расширение существующего `TenantSLO`)

### Type
**new_capability** (built-in Temporalio SDK + existing internal lib, без новых deps)

### Library
N/A — расширение существующего `src/backend/core/tenancy/slo.py` через Temporal SDK `ContinueAsNew` + существующего `TokenBudget`.

### Evidence (post f57c54b8)
- `src/backend/core/tenancy/slo.py:53` — `TenantSLO.for_tenant(tenant_id)` уже возвращает per-tenant SLO override (latency, error_rate, availability)
- Но Temporal workflows (`src/backend/infrastructure/workflow/`) **не вызывают** `TokenBudget.reserve()` перед шагами — это закрыто только для LLM-вызовов через `BudgetEnforcer` (`src/backend/core/tenancy/budget_enforcer.py:35`)
- T4 (Temporal versioning 196fd2e2) открыл worker-versioning, но pre-flight budget check отсутствует
- Multi-tenant Temporal workflow в проде может превысить budget без pre-check

### Estimated impact
- **LOC reduction**: 0% (net add), но предотвращает ~5 LOC на каждом новом workflow-step для ручного budget-check
- **Capability gain**: temporal workflows автоматически fail-fast при превышении tenant budget (через `Activity.heartbeat` cancellation); multi-tenancy enforcement становится consistent с LLM/DB/Redis слоями
- **Effort**: M (2-3 sprint-days; требует Temporal `StartActivity` cancellation test + per-tenant metric export)
- **Risk**: 5 (Temporal cancellation cascade требует тщательного тестирования; non-trivial — workflow idempotency на cancelled activity)

### Scores
- Library match: **N/A** (built-in Temporalio SDK + existing internal lib)
- Fit with philosophy: **10/10** (multi-tenancy + async-first + capability-gated через существующий `BudgetEnforcer` интерфейс)

### Why now
M7 Integration Layer (commits 8038907-0ea7b28) завершил multi-protocol; multi-tenancy для новых Temporal workflows — natural next step. P1-7 «per-tenant temporal budget» в бэклоге multi-agent аудита.

### Concerns / mitigations
- `temporalio>=1.27` — extra dep, но уже в core deps (line 375 pyproject.toml)
- Нужно согласование с Temporal best-practice (cancellation vs fail-fast)

---

## Sources consulted

- `pyproject.toml` (deps inventory: lines 10-146, 148-530, 532-581)
- `src/backend/services/audit/clickhouse_audit_service/service.py:1-275` (current post-T1 implementation)
- `src/backend/entrypoints/middlewares/idempotency.py:1-180` (RedisNxBackend)
- `src/backend/core/resilience/retry.py:1-276` (canonical retry surface — already on tenacity)
- `src/backend/core/tenancy/__init__.py:1-90` + `slo.py` + `token_budget.py` + `budget_enforcer.py` (multi-tenancy primitives)
- `src/backend/infrastructure/scheduler/scheduler_manager.py:1-311` (T3 fixed commit efdda246 reference)
- Git log f57c54b8..44e64c15 (P0 audit closure context)
- `AGENTS.md` (Ponytail rules + architecture constraints)
- `docs/compose/reports/2026-08-05-multi-agent-domain-audit.md` (P1-P4 backlog)

## Not proposed (out of scope или YAGNI)

- **slowapi / flask-limiter**: уже покрыто `fastapi-limiter>=0.1.6` (line 36 pyproject) + `global_ratelimit.py` обёрткой — замена ничего не даёт
- **starlette-exporter / prometheus-client**: уже используются (lines 35, 128)
- **replacing custom `croniter` wrappers**: `croniter>=6.2.0` (line 66) уже canonical
- **httpx → aiohttp**: ADR-0253 + commit 24aa0ff7 закрыли это (Round 61-63)
- **Custom OpenTelemetry helpers**: OTel SDK уже в deps (lines 44-52) и используется через auto-instrumentation — замена даёт <10% LOC reduction
- **New ASGI middleware framework** (типа Starlite): выходит за рамки Ponytail — текущий registry в `entrypoints/middlewares/registry.py` уже покрывает 30+ middleware
- **Custom CSV reader**: `aiohttp` заменён на `httpx` в R61; CSV processing через Camel HTTP уже покрыт; дублирование через `pandas`/`polars` — YAGNI (есть `analytics` extra)

## Findings worth promoting

- В стеке **уже есть** `tenacity`, `purgatory`, `asgi-idempotency-header`, `fastapi-limiter`, `croniter` — все стандартные retry/idempotency/rate-limit/cron задачи закрыты библиотеками; новые proposal'ы должны либо **завершать их adoption** (#1, #2), либо **строить capability поверх** (#3)
- `purgatory.backends.disk.DiskBackend` уже используется для scheduler DLQ (после commit efdda246 / T3) — это создаёт precedent для audit-DLQ unification в Proposal #1
- `BudgetEnforcer` интерфейс (`core/tenancy/budget_enforcer.py:35`) — готовый extension point для Proposal #3 без новых abstraction layers

## Status

- ✅ Все 3 утверждены пользователем (2026-08-05)
- ⏳ Открыты task-tracker записи T7, T8, T9 для последующей имплементации
