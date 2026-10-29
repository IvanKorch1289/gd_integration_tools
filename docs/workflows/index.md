# Workflows

Temporal (production) + LiteTemporalBackend (dev_light).

## Терминология

* **Шаг** (step) — **основной термин**. Шаг — одна декларация в `steps[]`
  workflow: `type: activity`, `type: saga`, `type: wait_signal`,
  `type: sleep`, `type: pause`, `type: resume` и т.д. У шага есть
  собственные `timeout_s`, `retry_policy`, `output_key`; шаг — единица
  исполнения, retry и step-level события (`step_started` /
  `step_finished` / `step_failed`).
* **Этап** (stage) — **крупная фаза** workflow, объединяющая несколько
  шагов (например, «этап скоринга» = `activity` + `activity` + `saga`).
  Этап — понятийная надстройка для текста и имён шагов; **отдельной
  сущности в коде этапа нет**: в декларации нет поля `stage`, в union
  `WorkflowStep` типа `stage` не существует.

В YAML и в Python-builder используется только «шаг» (`steps[]`); слово
«этап» появляется только в описаниях крупных фаз. Смешение терминов
«step»/«stage» в runbook'ах и туториалах — дефект документации, а не
API.

## Архитектура

Workflow-подсистема разложена по четырём слоям (каталога `workflows/` на
уровне `src/backend/` **не существует**):

```
src/backend/core/workflow/            # протоколы backend'а, компенсации, fake-backend
├── backend.py                        # WorkflowBackend (Protocol)
├── compensation.py                   # saga-компенсации
└── fake_backend.py                   # in-memory backend для тестов

src/backend/dsl/workflow/              # декларации, builder, компиляция
├── builder/                          # WorkflowBuilder (fluent API)
├── spec/                             # WorkflowDeclaration + union шагов (14 типов)
│   ├── activity_declarations.py      # activity / call_function / saga / pause / resume / wait_signal / sleep
│   ├── advanced_declarations.py      # sensor / agent / reflect / checkpoint / guardrail / escalate
│   └── workflow.py                   # WorkflowStep (discriminator = "type")
├── compiler/                         # emitter, activity_bridge, gateways
│   ├── emitter.py                    # WorkflowDeclaration → Temporal @workflow.defn
│   ├── activity_bridge.py            # обёртка activity + capability-guard
│   └── gateways.py                   # runtime-компиляторы XOR/AND/OR
├── gateways.py                       # BranchSpec / GatewaySpec
├── yaml_io.py                        # load_workflow_from_yaml / to_yaml
└── ...                               # launcher, orchestrator, versioning, visualize, dryrun

src/backend/infrastructure/workflow/  # бэкенды исполнения + реестр
├── temporal_backend.py               # production Temporal
├── lite_temporal_backend.py          # dev_light (in-process)
├── pg_runner_backend.py              # durable-runner на Postgres
├── registry.py                       # workflow_registry (descriptor + route_id)
├── executor/, pg_runner_internals/   # исполнение шагов и работа с event log
├── middlewares/                      # step_audit (не подключён — см. «Не реализовано»)
└── worker.py, temporal_worker_runtime.py, versioning/

src/backend/services/workflows/       # прикладные сервисы поверх workflow
├── facade.py                         # WorkflowFacade (сигналы, запуск, отмена)
├── hitl_service.py                   # pending-сигналы HITL
├── hitl_signal_store.py              # хранилище сигналов (in-memory / Redis)
├── sla_alerting.py                   # SlaTracker / SlaPolicy
└── saga_history.py                   # timeline saga-компенсаций
```

Подробная карта — [Workflow-архитектура](../architecture/workflow_architecture.md).

## DSL

Запуск workflow из DSL-роута (`RouteBuilder.invoke_workflow`):

```python
from src.backend.dsl.builders import RouteBuilder

route = (
    RouteBuilder("credit_check_flow")
    .invoke_workflow(
        "credit_check.full",
        mode="async-api",
        args={"applicant_id": "${body.applicant_id}"},
        namespace="default",
        task_queue="default",
        result_property="workflow_result",
        invocation_id_property="invocation_id",
        reply_timeout_seconds=60.0,
    )
    .build()
)
```

Сигнатура `invoke_workflow` (см.
`src/backend/dsl/builders/integration_core/workflow_mixin.py`):

| Параметр | По умолчанию | Назначение |
|---|---|---|
| `name` | — | Логическое имя workflow (обязательный позиционный). |
| `mode` | `"async-api"` | `"sync"` / `"async-api"` / `"async-reply"`. |
| `args` | `None` | Аргументы запуска; `None` → `in_message.body`. |
| `namespace` | `"default"` | Temporal namespace. |
| `task_queue` | `"default"` | Temporal task queue. |
| `result_property` | `"workflow_result"` | Куда писать результат/handle. |
| `invocation_id_property` | `"invocation_id"` | Куда писать `workflow_id`. |
| `reply_timeout_seconds` | `60.0` | Таймаут для `mode="async-reply"`. |
| `version` | `None` | SemVer-диапазон (например `">=1.0,<2.0"`). |

Параметров `wait` и `timeout` у метода **нет** — ожидание реализуется
через `mode` и `reply_timeout_seconds`.

## Декларация workflow

Python-builder (шаги = `ActivityDeclaration`; у `BranchSpec` обязателен
`name`):

```python
from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.gateways import BranchSpec
from src.backend.dsl.workflow.spec import ActivityDeclaration

wf = (
    WorkflowBuilder("credit_decision")
    .default_timeout(120.0)
    .activity("fetch_credit_score", args={"applicant_id": "${{ applicant_id }}"})
    .gateway_xor(
        BranchSpec(
            name="high",
            condition="score >= 700",
            steps=[ActivityDeclaration(name="approve_loan")],
        ),
        BranchSpec(
            name="low",
            condition="score < 700",
            steps=[ActivityDeclaration(name="reject_loan")],
        ),
    )
    .activity("send_notification")
    .build()
)
```

YAML (discriminator шага — поле `type`; в union `WorkflowStep` 14 типов,
`gateway` среди них **нет** — gateway кодируется как activity с
`args.gateway`):

```yaml
name: credit_decision
version: "1.0"
default_timeout_s: 120
steps:
  - type: activity
    name: fetch_credit_score
    args:
      applicant_id: "${{ applicant_id }}"
    timeout_s: 30
  - type: activity
    name: __gateway__xor_0
    args:
      gateway:
        kind: xor
        branches:
          - name: high
            condition: "score >= 700"
            steps:
              - type: activity
                name: approve_loan
          - name: low
            condition: "score < 700"
            steps:
              - type: activity
                name: reject_loan
  - type: activity
    name: send_notification
```

Поддерживаемые типы шагов (`type`): `activity`, `call_function`, `saga`,
`wait_signal`, `sleep`, `pause`, `resume`, `sensor`, `agent_invoke`,
`reflect`, `checkpoint`, `guardrail`, `escalate`, `continue_as_new`.

Шаг `call_function` — прямой вызов module-level функции `module:fn`
(без обёртки в `ActionHandlerRegistry`); в YAML у него поле `ref`
вместо `name`. Если в шаге `type: activity` указать `name` вида
`module:fn`, декларация нормализуется в `type: call_function` — поэтому
`required_capabilities` у таких шагов недоступны (у `call_function` нет
такого поля).

Плейсхолдеры в `args` пишутся в DSL-форме `"${{ <path> }}"` (как в
`extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml`);
формы `"${...}"` — это placeholder'ы уровня RouteBuilder, не workflow-DSL.

## Capability-гейт workflow-активити

Шаг `activity` может объявить требуемые capability:

```yaml
steps:
  - type: activity
    name: fetch_credit_score
    required_capabilities: ["net.outbound"]
```

`required_capabilities` (поле `ActivityDeclaration`) проверяется в
`src/backend/dsl/workflow/compiler/activity_bridge.py`: активность
оборачивается в `capability_guarded_activity(...)` **до** регистрации в
Temporal, поэтому отказ происходит fail-closed с
`CapabilityDeniedError` до вызова activity. Если runtime-контекст
плагина недоступен — тоже deny (fail-closed).

Namespace для проверки определяет runtime-резолвер ADR-0366: `route_id`
роута → fallback `"core"` (baseline) → fail-closed DENY. В prod/staging
гейт включён, core-baseline выключен — см.
[Capability runtime](../explanation/capability_runtime.md).

## Схема состояний

Статусы инстанса — `WorkflowStatus`
(`src/backend/core/domain/models/workflow_instance.py`):

| Статус | Значение | Что означает |
|---|---|---|
| `pending` | создан | Инстанс создан, первый шаг ещё не начат (worker не подхватил). |
| `running` | выполняется | Workflow активно исполняется worker'ом. |
| `paused` | приостановлен | Ждёт внешнего события / таймера (`wait_signal`, `pause`). |
| `succeeded` | успешно | Терминальный успешный статус. |
| `failed` | ошибка | Терминальный статус: все retry исчерпаны. |
| `cancelling` | отменяется | Получен сигнал cancel, идёт graceful stop. |
| `cancelled` | отменён | Терминальный статус после отмены. |
| `compensating` | компенсация | Выполняются Saga-компенсации отката. |

Переходы:

```
pending ──► running ──► succeeded
              │  │
              │  ├──► failed
              │  ├──► paused ──► running
              │  └──► cancelling ──► cancelled
              └──► compensating ──► failed | cancelled
```

Инстанс и его события хранятся в Postgres: `workflow_instances`
(header) и `workflow_events` (append-only event log, `seq` +
`step_name` + `event_type`). Типы событий —
`src/backend/core/domain/models/workflow_event.py`: instance-level
(`created`, `paused`, `resumed`, `cancelled`, `snapshotted`),
step-level (`step_started`, `step_finished`, `step_failed`,
`branch_taken`, `compensated`) и `signal_received`.

## Как отладить

Admin-API (`/api/v1/admin/workflows/...`) требует admin-роль
(operator / super_admin).

```bash
# 1. Список инстансов с фильтром по статусу
curl -s "http://localhost:8000/api/v1/admin/workflows?status=running&limit=50"

# 2. Детали инстанса: header + snapshot + полный event log
curl -s "http://localhost:8000/api/v1/admin/workflows/<instance_id>"

# 3. Пагинированный event log (длинные workflow)
curl -s "http://localhost:8000/api/v1/admin/workflows/<instance_id>/events?after_seq=0&limit=100"

# 4. Форсированный retry упавшего workflow (202 Accepted)
curl -s -X POST "http://localhost:8000/api/v1/admin/workflows/<instance_id>/retry"

# 5. Graceful cancel (202 Accepted, тело опционально)
curl -s -X POST "http://localhost:8000/api/v1/admin/workflows/<instance_id>/cancel" \
  -H "Content-Type: application/json" \
  -d '{"reason": "operator escalation"}'

# 6. Возобновить paused workflow (202 Accepted)
curl -s -X POST "http://localhost:8000/api/v1/admin/workflows/<instance_id>/resume"

# 7. Timeline saga-компенсаций
curl -s "http://localhost:8000/api/v1/admin/workflows/<workflow_id>/saga-history?limit=50"

# 8. Запуск workflow по имени (wait=false → 202 Accepted + instance_id)
curl -s -X POST "http://localhost:8000/api/v1/admin/workflows/trigger/credit_decision" \
  -H "Content-Type: application/json" \
  -d '{"applicant_id": "applicant-42"}'

# 9. Тот же запуск с ожиданием терминального статуса (timeout_s: 1..600)
curl -s -X POST \
  "http://localhost:8000/api/v1/admin/workflows/trigger/credit_decision?wait=true&timeout_s=60" \
  -H "Content-Type: application/json" \
  -d '{"applicant_id": "applicant-42"}'
```

Ответ `trigger` — `WorkflowInstanceRef`: `id`, `workflow_name`,
`status` (один из восьми статусов выше), `created_at`, `result`
(только при `wait=true` и успехе), `error`.

Важно: `/api/v1/invocations` — **не** API запуска workflow. Он требует
тело `{"action": ..., "payload": {...}, "mode": ...}` и отвечает
`status` из набора `ok | accepted | error`. Эти статусы — не статусы
workflow; для workflow используйте admin-API (см. выше).

## Режимы

- **Production**: Temporal.io cluster
- **dev_light**: LiteTemporalBackend (in-process)
- **Durable runner**: `pg_runner_backend.py` — исполнение поверх Postgres

## Возможности

- HITL (Human-in-the-loop) signals — `wait_signal`, `services/workflows/hitl_service.py`
- Saga compensations (LRA pattern) — `type: saga`
- Subworkflows — `RouteBuilder.sub_workflow(...)` (`mode="async-api"`)
- Pause/resume/continue — `type: pause` / `type: resume` / `type: continue_as_new`
- Failure recovery — `retry_policy`, admin-API `retry`
- Retry policies (exponential backoff) — `spec/policies.py`
- Async, parallel, sequential — `mode`, `gateway_and` / `gateway_xor` / `gateway_or`

## Не реализовано

* `SlaTracker` (`src/backend/services/workflows/sla_alerting.py`) — класс
  существует, но **нигде не инстанцируется**: ни в `lifespan`, ни в
  worker'ах, ни в composition root. `WorkflowFacade` принимает
  `sla_tracker` только как опциональный параметр, а сам фасад в `src/`
  пока не создаётся. SLA-алертинг (email/Slack escalation по
  `soft_limit_seconds` / `hard_limit_seconds`) в рантайме не работает.
* `escalate` (`type: escalate`) и downstream-эскалация — объявлены в
  union шагов, но отдельного исполнителя эскалации в проде нет.
* Audit-события **по шагам** в ClickHouse/Redis не пишутся: middleware
  `StepAuditMiddleware`
  (`src/backend/infrastructure/workflow/middlewares/step_audit.py`)
  существует, но нигде не инстанцируется и не подключён к runner'у —
  записи в `workflow_step_log` не уходят (флаг
  `feature_flags.workflow_step_log_enabled` это не меняет — включать
  нечего). Instance-level event log (`workflow_events`) при этом
  работает.

Owner-задачи: SLA-alerting и step-level audit — K3 DSL+Workflow
(GAP-WF-4.5 и follow-up wave 18); точные идентификаторы — в
`docs/roadmap/PROD_READINESS_GAPS.md`.

## См. также

- [DSL](../dsl/index.md)
- [Workflow-архитектура](../architecture/workflow_architecture.md)
- [Worker Versioning](worker-versioning.md)
- [Runbook: HITL stuck workflow](../runbooks/hitl-stuck-workflow.md)
- [Tutorial 04 — Temporal workflow](../tutorials/04_temporal_workflow.md)
