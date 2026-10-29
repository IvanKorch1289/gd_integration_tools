# Tutorial 04 — Temporal workflow с XOR/AND gateways

> **Prerequisites:** Tutorial 02 (first plugin). Temporal сервер запущен.
> ~45 минут.

## Цель

Создать workflow с branch-логикой через WorkflowBuilder fluent API,
зарегистрировать его в реестре workflow'ов, запустить из admin-API.

Термины: **шаг** (step) — одна декларация в `steps[]`; **этап** (stage) —
крупная фаза из нескольких шагов. В коде есть только шаги; см.
[Workflows → Терминология](../workflows/index.md#терминология).

## Шаги

### 1. Декларация workflow в Python

У `BranchSpec` обязателен `name`, а шаг внутри ветки — это
`ActivityDeclaration` (класса `Activity` в проекте нет).

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

Условие gateway вычисляется через `simpleeval` по outputs'ам шагов:
`score` — это `output_key` шага, который положил значение в контекст.

### 2. Альтернативно — YAML

YAML-декларация парсится функцией `load_workflow_from_yaml`
(`src/backend/dsl/workflow/yaml_io.py`). Обязателен discriminator шага —
поле `type`; в union `WorkflowStep` 14 типов, `gateway` среди них **нет**:
gateway кодируется как activity с `args.gateway`.

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

Плейсхолдеры в `args` — в DSL-форме `"${{ <path> }}"` (как в
`extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml`).
Форма `"${input.id}"` — это placeholder уровня RouteBuilder, в
workflow-DSL она не резолвится.

### 3. Зарегистрировать workflow в реестре

Реестр — `workflow_registry`
(`src/backend/infrastructure/workflow/registry.py`): хранит
`WorkflowDescriptor` и связку `workflow_name → route_id`. Без этой
связки admin-API вернёт 500 (`missing route_id binding`).

```python
from src.backend.infrastructure.workflow.registry import (
    WorkflowDescriptor,
    workflow_registry,
)

workflow_registry.register(
    WorkflowDescriptor(
        name="credit_decision",
        description="Кредитное решение по заявке",
        tags=("banking",),
    ),
    route_id="workflow:credit_decision",
)
```

Temporal-исполнение подключается отдельным шагом: скомпилированный
декларацией класс (`compile_workflow` в
`src/backend/dsl/workflow/compiler/emitter.py`) регистрируется в worker'е
пула `TemporalWorkerPool` (`src/backend/infrastructure/workflow/temporal_client.py`):

```python
from src.backend.infrastructure.workflow.temporal_client import (
    TemporalClientFactory,
    TemporalWorkerPool,
)

factory = TemporalClientFactory(target_host="localhost:7233")
pool = TemporalWorkerPool(factory=factory, namespace="default")
await pool.register_worker(
    task_queue="credit-queue",
    workflows=[compiled_workflow_class],
    activities=[fetch_credit_score, approve_loan, reject_loan, send_notification],
)
```

`register_worker` требует живой Temporal-сервер — этот блок нельзя
выполнить офлайн.

### 4. Запуск из admin-API

Workflow запускается **не** через `/api/v1/invocations`: этот эндпоинт
принимает тело `{"action": ..., "payload": {...}, "mode": ...}` и отвечает
статусом из набора `ok | accepted | error` — это статусы вызова, а не
workflow.

```bash
curl -X POST http://localhost:8000/api/v1/admin/workflows/trigger/credit_decision \
  -H "Content-Type: application/json" \
  -d '{"applicant_id": "applicant-42"}'
# {"id":"wf-12345","workflow_name":"credit_decision","status":"pending","created_at":"..."}
```

Опционально — дождаться терминального статуса (`wait=true`,
`timeout_s` от 1 до 600 секунд):

```bash
curl -X POST \
  "http://localhost:8000/api/v1/admin/workflows/trigger/credit_decision?wait=true&timeout_s=60" \
  -H "Content-Type: application/json" \
  -d '{"applicant_id": "applicant-42"}'
```

### 5. Проверить результат

```bash
curl -s http://localhost:8000/api/v1/admin/workflows/wf-12345
```

Ответ — `WorkflowInstanceDetailSchemaOut`: `status` (один из
`pending`, `running`, `paused`, `succeeded`, `failed`, `cancelling`,
`cancelled`, `compensating`), `snapshot_state` и полный `events` (event
log). Статуса `completed` в системе нет — успешный статус называется
`succeeded`.

Пагинированный event log (для длинных workflow):

```bash
curl -s "http://localhost:8000/api/v1/admin/workflows/wf-12345/events?after_seq=0&limit=100"
```

Разбор и отладка — в разделе
[Workflows → Как отладить](../workflows/index.md#как-отладить).

## What's next?

* Tutorial 05 — HITL workflow с wait_signal.
* Tutorial 11 — ClickHouse audit sink.
* [Workflows → Схема состояний](../workflows/index.md#схема-состояний).
