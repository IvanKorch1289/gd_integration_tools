# Workflow-архитектура

> Канон: [Workflows](../workflows/index.md) — пользовательский контракт.
> Здесь — карта модулей и границы слоёв. Общая карта репозитория:
> [Canonical Module Map](canonical-module-map.md).

## Слои

Workflow-подсистема разложена по четырём слоям. Каталога
`workflows/` на уровне `src/backend/` **не существует** — это была
ошибка ранней документации.

| Слой | Каталог | Что внутри | Публичный вход |
|---|---|---|---|
| Контракты | `src/backend/core/workflow/` | `WorkflowBackend` (Protocol), saga-компенсации, fake-backend | `from src.backend.core.workflow import ...` |
| Runtime / DSL | `src/backend/dsl/workflow/` | декларации, builder, компиляция в Temporal, gateway'и | `WorkflowBuilder`, `load_workflow_from_yaml` |
| Бэкенды | `src/backend/infrastructure/workflow/` | Temporal, LiteTemporal, PG-runner, реестр, worker'ы | `workflow_registry`, `TemporalWorkerPool` (через DI-facade) |
| Прикладные сервисы | `src/backend/services/workflows/` | HITL, SLA-alerting, saga-history, cost-estimator | `HitlService` и т.п. |

Правило слоёв то же, что и в остальном проекте: `core` не импортирует
`infrastructure` напрямую; наружу бэкенды отдаются через
`core/di/providers/workflow.py` (`get_workflow_provider()`).

## Runtime / DSL — `src/backend/dsl/workflow/`

| Модуль | Роль |
|---|---|
| `spec/workflow.py` | `WorkflowDeclaration` + union `WorkflowStep` (14 типов, discriminator — поле `type`). |
| `spec/activity_declarations.py` | `activity`, `call_function`, `saga`, `pause`, `resume`, `wait_signal`, `sleep`; поле `required_capabilities` (у `activity`). |
| `spec/advanced_declarations.py` | `sensor`, `agent_invoke`, `reflect`, `checkpoint`, `guardrail`, `escalate`, `continue_as_new`. |
| `spec/policies.py` | `RetryPolicy`, `SlaPolicy`, `MemoryScope`. |
| `builder/` | Fluent `WorkflowBuilder` (activity, gateway_xor/and/or, wait_for_signal, pause/resume, saga, sla, reflect/checkpoint/guardrail/escalate). |
| `compiler/emitter.py` | `WorkflowDeclaration` → Temporal `@workflow.defn`-класс. |
| `compiler/activity_bridge.py` | Регистрация activity + capability-guard (`required_capabilities`). |
| `compiler/gateways.py` | Runtime-компиляторы XOR / AND / OR. |
| `gateways.py` | `BranchSpec` / `GatewaySpec` / `GatewayCompiler`. |
| `yaml_io.py` | `load_workflow_from_yaml` / `to_yaml` / `diff`. |

Gateway в YAML не является отдельным типом шага: union содержит 14
типов, `gateway` среди них нет. Gateway кодируется как шаг
`type: activity` с `args.gateway` (`kind` + `branches`) — это делает
BPMN-импортёр и Python-builder (`gateway_xor`/`gateway_and`/`gateway_or`).

## Бэкенды — `src/backend/infrastructure/workflow/`

| Модуль | Роль |
|---|---|
| `temporal_backend.py` | Production: Temporal.io cluster. |
| `lite_temporal_backend.py` | dev_light: in-process, без внешнего сервиса. |
| `pg_runner_backend.py` | Durable-runner поверх Postgres (`workflow_instances` + `workflow_events`). |
| `registry.py` | `workflow_registry`: `WorkflowDescriptor` + связка `workflow_name → route_id`. |
| `worker.py`, `temporal_worker_runtime.py` | Temporal-worker и его runtime. |
| `executor/`, `pg_runner_internals/` | Исполнение шагов и работа с event log. |
| `versioning/` | Worker Versioning (BuildID pinning). |
| `outbox_worker.py`, `compensating_driver.py`, `saga_state.py` | Outbox, saga-компенсации. |

## Прикладные сервисы — `src/backend/services/workflows/`

| Модуль | Роль |
|---|---|
| `hitl_service.py` + `hitl_signal_store*.py` | Pending-сигналы HITL (in-memory / Redis), resolve, pub/sub. |
| `facade.py` | `WorkflowFacade` — запуск/сигнал/отмена workflow. |
| `sla_alerting.py` | `SlaPolicy` / `SlaTracker` — **трекер нигде не инстанцируется** (см. ниже). |
| `saga_history.py` | Timeline saga-компенсаций для admin-API. |
| `cost_estimator.py`, `template_registry.py` | Оценка стоимости и шаблоны workflow. |

## Персистентность

| Таблица | Назначение |
|---|---|
| `workflow_instances` | Header инстанса: `status`, `current_version`, `last_event_seq`, `snapshot_state`, `input_payload`. |
| `workflow_events` | Append-only event log: `seq`, `event_type`, `step_name`, `payload`, `occurred_at`. |

Статусы инстанса — `WorkflowStatus`
(`src/backend/core/domain/models/workflow_instance.py`): `pending`,
`running`, `paused`, `succeeded`, `failed`, `cancelling`, `cancelled`,
`compensating`. Полная схема переходов — в
[Workflows → Схема состояний](../workflows/index.md#схема-состояний).

## Точки входа

| Точка | Что делает |
|---|---|
| `POST /api/v1/admin/workflows/trigger/{workflow_name}` | Запуск workflow по имени (с опциональным `wait`/`timeout_s`). |
| `GET /api/v1/admin/workflows/{instance_id}` | Header + snapshot + event log. |
| `GET /api/v1/admin/workflows/{instance_id}/events` | Пагинированный event log. |
| `POST /api/v1/admin/workflows/{instance_id}/retry|cancel|resume` | Управление жизненным циклом инстанса. |
| `GET /api/v1/admin/workflows/{workflow_id}/saga-history` | Timeline saga-компенсаций. |
| `POST /api/v1/hitl/{signal_id}/resolve` | Разрешение HITL-сигнала. |
| `RouteBuilder.invoke_workflow(...)` | Запуск workflow из DSL-роута. |

## Не реализовано (owner-задачи)

* `SlaTracker` (`services/workflows/sla_alerting.py`) — класс есть,
  инстанцирования нет: SLA-алертинг и email/Slack-эскалация в рантайме
  не работают. Owner: K3 DSL+Workflow (GAP-WF-4.5).
* Step-level audit-события (по шагам) — не эмитятся ни в ClickHouse, ни
  в Redis. `StepAuditMiddleware`
  (`infrastructure/workflow/middlewares/step_audit.py`) существует, но не
  инстанцируется и не подключён к runner'у; instance-level event log
  (`workflow_events`) при этом есть. Owner: K3 DSL+Workflow, follow-up
  wave 18.
* `escalate` (`type: escalate`) — объявлен в union шагов, но отдельного
  исполнителя эскалации нет.

## См. также

* [Workflows](../workflows/index.md) — DSL, схема состояний, «как отладить».
* [Worker Versioning](../workflows/worker-versioning.md).
* [Tutorial 04 — Temporal workflow](../tutorials/04_temporal_workflow.md).
* [Runbook: HITL stuck workflow](../runbooks/hitl-stuck-workflow.md).
