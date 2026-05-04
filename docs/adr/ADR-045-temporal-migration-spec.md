# ADR-045: Temporal как default workflow-backend (Wave C)

- **Статус:** proposed
- **Дата:** 2026-05-04
- **Фаза:** R1 / V11 — Wave C
- **Автор:** v11-architect

## Контекст

ADR-031 ввёл durable workflows как DSL-расширение поверх собственного
runner'а: event-sourcing в PostgreSQL (`workflow_instances` +
`workflow_events`), `LISTEN/NOTIFY` + advisory-lock воркеры, APScheduler
для отложенных шагов. Это закрыло уход с Prefect.

По мере роста сценариев (V11.1 — workflow как primitive ядра, ADR-044
— capability `workflow.start` / `workflow.signal`) упёрлись в:

1. **Fan-out / parallelism** — `for_each(parallel=True)` ограничена
   одним процессом; в Temporal — нативные child workflows и activity-
   fan-out.
2. **Signal / Query** — через polling `workflow_events`; нет low-latency
   push и typed queries без записи в БД.
3. **Replay-семантика** — наш replay не гарантирует детерминированное
   переисполнение при изменении spec'а.
4. **Cross-language activities** — Temporal SDK покрывает Go/Java/TS,
   собственный runner это не закроет.
5. **Versioning** — Temporal `patched()` / Build IDs дают зрелую модель;
   в ADR-031 это TBD.

V11.1 фиксирует: workflow становится primitive ядра, backend выбирается
через protocol. Default — Temporal; pg-runner остаётся как dev/staging
fallback (R3).

## Рассмотренные варианты

- **Вариант 1 — оставить ADR-031 (own pg-runner) как единственный
  backend.** Плюсы: работает, без новых deps. Минусы: не решает
  ограничения 1–5; cross-language невозможен; versioning с нуля;
  signal/query через БД нагружают её под mq-семантику.

- **Вариант 2 — полная миграция на Temporal без protocol-обёртки.**
  Плюсы: минимум кода, прямой `temporalio` API. Минусы: ядро
  hard-coupled с Temporal SDK; нет dev-light без кластера;
  big-bang-миграция всех existing workflows.

- **(Recommended) Вариант 3 — `WorkflowBackend` Protocol + Temporal
  default + pg-runner-fallback.** Плюсы: ядро видит только Protocol
  (тестируемо `FakeWorkflowBackend`); смена backend через DI;
  gradual rollout; dev-light без Temporal. Минусы: один лишний
  method-call на activity; два impl'а в R1 → R3.

- **Вариант 4 — Prefect / Airflow.** V10 уже отказались от Prefect
  (heavy dep, отдельный server); Airflow — batch-ETL, не event-driven.
  Отбрасывается.

## Решение

Принят **Вариант 3** — `WorkflowBackend` Protocol + Temporal default
impl + `PgRunnerWorkflowBackend` (обёртка над ADR-031-runner) как
fallback для dev/staging.

### `WorkflowBackend` Protocol

Целевой модуль: `src/core/workflow/backend.py`. Минимальные операции
без знания о конкретном SDK:

```python
from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class WorkflowHandle(BaseModel):
    """Дескриптор запущенного workflow-инстанса."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    run_id: str
    namespace: str  # tenant-id или global


class WorkflowResult(BaseModel):
    """Финальный результат await_completion()."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: dict[str, Any]
    status: str  # "completed" | "failed" | "cancelled" | "timed_out"
    failure: dict[str, Any] | None = None


@runtime_checkable
class WorkflowBackend(Protocol):
    """Унифицированный контракт workflow-движка для ядра."""

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle: ...

    async def signal_workflow(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        payload: dict[str, Any],
    ) -> None: ...

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None: ...

    async def await_completion(
        self,
        *,
        handle: WorkflowHandle,
        timeout: timedelta | None = None,
    ) -> WorkflowResult: ...

    async def replay(
        self,
        *,
        workflow_name: str,
        history: bytes,
    ) -> None:
        """Прогнать историю через текущий код — для CI versioning gate."""
        ...
```

### `TemporalWorkflowBackend` (default)

Обёртка над `temporalio.client.Client` + `temporalio.worker.Worker`:

- `namespace` мапится на `TenantContext.tenant_id`; cross-tenant
  signal по умолчанию `deny` (см. открытые вопросы).
- `task_queue` берётся из `route.toml` → `[workflow] task_queue`.
- DataConverter поверх orjson (ADR-007 perf-sweep), bytes-stable.
- Activity вызывают capability-checked фасады ядра — gate работает
  на уровне activity, не workflow.

### `PgRunnerWorkflowBackend` (legacy fallback)

Тонкая обёртка над `DurableWorkflowRunner` (ADR-031). Используется
в dev-light (нет Temporal-кластера), staging до Wave D-миграции,
ResilienceCoordinator-fallback (см. открытые вопросы).

`signal_workflow` → `INSERT workflow_events(event_type=
"signal_received")` + `pg_notify`. `query_workflow` → snapshot-read
из `workflow_instances.snapshot_state` (degraded vs Temporal —
не видит in-flight activity).

### Workflow definitions = DSL-route + `.workflow_step(...)`

Workflow остаётся декларативным: один route с `[[capabilities]]`,
control-flow processors из ADR-031 (`branch`/`loop`/`sub_workflow`)
плюс новый `workflow_step` — обёртка, регистрируемая backend'ом
как activity. Полный DSL-API — в Wave D-ADR.

### Capability integration

Route, стартующий workflow, декларирует:

```toml
[[capabilities]]
name = "workflow.start"
scope = "credit.score.*"

[[capabilities]]
name = "workflow.signal"
scope = "credit.score.*"
```

`RouteLoader.register()` (см. ADR-044 §inheritance) проверяет: (1)
capability присутствует, (2) `scope` покрывает фактический
`workflow_id` через `GlobScopeMatcher`, (3) route ⊆ plugins.
Runtime-фасад `WorkflowFacade.start(...)` дополнительно дёргает
`CapabilityGate.check(plugin, "workflow.start", workflow_id)`.

### Versioning (TBD → R3)

В Wave C — placeholder: `route.toml` получает опц. `[workflow.version]
semver = "1.0.0"`. Финальная схема (Temporal Build IDs vs наш semver)
— в R3, см. открытые вопросы.

## Phase plan (Wave C / D / R3)

- **Wave C (этот ADR + protocol + tests scaffold).** Зафиксировать
  `WorkflowBackend` Protocol, `FakeWorkflowBackend` для тестов;
  existing pg-runner работает без изменений.
- **Wave D (`TemporalWorkflowBackend` impl + миграция).** Поднять
  testcontainers `temporalite` на CI; реализовать impl; мигрировать
  existing workflows; ADR-031 → `Status: superseded by ADR-045`.
- **Wave R3 (versioning + replay-job).** Финализировать
  versioning-схему; CI replay-gate; удалить pg-runner-fallback.

## Trade-off

- **Temporal как зависимость.** Heavy dep `temporalio` (~25MB wheel)
  + testcontainers `temporalite` на CI. Митигация: ленивый импорт
  внутри `TemporalWorkflowBackend.__init__`; dev-light без SDK.
- **Protocol overhead.** +1 method-call на activity. На фоне network
  round-trip к Temporal-серверу — пренебрежимо; мерить в Wave D.
- **Legacy ADR-031 runner — fallback.** Дублирование кода в R1;
  удаление в R3 после стабилизации Temporal-флоу.
- **Migration cost.** Existing workflows переписать под Temporal
  determinism. Митигация: `tools/migrate_workflow_v11.py` (Wave D)
  + co-existence (часть на pg-runner, часть на Temporal — выбор
  через `WorkflowBackend` factory по route-настройке).
- **Capability scope.** `workflow.signal` со scope-glob
  `credit.score.*` покрывает любой instance этой семьи;
  per-instance scope (`credit.score.${instance_id}`) — TBD R3.

## Открытые вопросы (R1.1 fwd-ref)

- **Versioning схема.** Temporal Build IDs vs per-workflow semver
  в manifest? Build IDs дают automatic compatibility-graph; semver
  — явный contract. Решение в R3.
- **Cross-tenant signal.** Default — deny. Нужна ли explicit
  allow-list для системных supervisor'ов? Решение R3.
- **Fallback chain.** Должен ли `ResilienceCoordinator` (ADR-036)
  переключать backend Temporal → pg-runner при отказе кластера?
  Это graceful degradation, но размывает гарантии (pg-runner не
  реализует все Temporal-семантики). Решение R3.

## Связанные ADR

- ADR-031 (durable workflows DSL) — будет **superseded by ADR-045**
  по факту имплементации в Wave D.
- ADR-036 (ResilienceCoordinator) — **связан**: workflow-failure
  → fallback chain (см. открытый вопрос).
- ADR-042 (plugin.toml) — **связан**: workflow-плагин декларирует
  `workflow.start` capability в манифесте.
- ADR-043 (route.toml) — **связан**: route, инициирующий workflow,
  декларирует capability и опц. `[workflow]` секцию (task_queue,
  version).
- ADR-044 (capability vocabulary) — **dependency**: использует
  `workflow.start` / `workflow.signal` из v0-каталога.
