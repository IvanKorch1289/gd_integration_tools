# Tutorial 05 — HITL workflow с approval signal

> **Prerequisites:** Tutorial 04. ~40 минут.

## Цель

Создать workflow, который ждёт human approval через signal. Operator
видит pending signal в HITL panel (страница 72) и approve/reject.

Термины: **шаг** (step) — одна декларация в `steps[]`; **этап** (stage) —
крупная фаза из нескольких шагов. См.
[Workflows → Терминология](../workflows/index.md#терминология).

## Шаги

### 1. Декларация workflow с wait_signal

```python
from src.backend.dsl.workflow.builder import WorkflowBuilder

wf = (
    WorkflowBuilder("loan_review_hitl")
    .activity("prepare_application_summary")
    .wait_for_signal(
        signal_name="hitl_approve",
        timeout_s=86400,  # 24h
        output_key="operator_decision",
    )
    .activity(
        "process_decision",
        args={"action": "${{ operator_decision.action }}"},
    )
    .build()
)
```

YAML-эквивалент (тип шага — `wait_signal`; в union `WorkflowStep` его
обязательное поле — `type`):

```yaml
name: loan_review_hitl
version: "1.0"
default_timeout_s: 300
steps:
  - type: activity
    name: prepare_application_summary
    timeout_s: 60
  - type: wait_signal
    signal_name: hitl_approve
    timeout_s: 86400
    output_key: operator_decision
  - type: activity
    name: process_decision
    args:
      action: "${{ operator_decision.action }}"
```

Если `timeout_s` не задан, ожидание сигнала бесконечно — workflow может
висеть сутками. Всегда задавайте таймаут (см.
[Runbook: HITL stuck workflow](../runbooks/hitl-stuck-workflow.md)).

### 2. Зарегистрировать pending signal в HitlService

В activity `prepare_application_summary` после подготовки summary:

```python
from src.backend.services.workflows.hitl_service import (
    HitlPendingSignal,
    HitlService,
    InMemoryHitlSignalStore,
)

hitl_service = HitlService(store=InMemoryHitlSignalStore())

await hitl_service.register_pending(
    HitlPendingSignal(
        signal_id="loan-review-42",
        workflow_id="loan-review-42",
        tenant_id="tenant-a",
        signal_name="hitl_approve",
        initiator="operator-a",
        title="Loan review #loan-42",
        payload={"amount": 100000, "score": 720},
    )
)
```

В prod вместо `InMemoryHitlSignalStore` используется
`RedisHitlSignalStore` (`src/backend/services/workflows/hitl_signal_store_redis.py`).
Внутри Temporal-activity `workflow_id` берётся из
`workflow.info().workflow_id`, а `tenant_id`/`initiator` — из
`TenantContext`.

### 3. Запустить workflow

Workflow запускается через admin-API (не через `/api/v1/invocations`:
тот эндпоинт требует `action`+`payload` и не знает про workflow).

```bash
curl -X POST http://localhost:8000/api/v1/admin/workflows/trigger/loan_review_hitl \
  -H "Content-Type: application/json" \
  -d '{"app_id": "loan-42"}'
# {"id":"wf-12345","workflow_name":"loan_review_hitl","status":"pending","created_at":"..."}
```

### 4. Operator approve через UI

* Открыть `http://localhost:8501` → страница `72_HITL_Panel`.
* Выбрать pending signal (если фильтруется — указать `tenant_id`).
* Заполнить `Operator name` + `Comment`, нажать `Approve`.

Страница скрыта, если выключен feature-flag
`feature_flags.hitl_panel_enabled` (дефолт — `True`; выключается
явно в профиле).

### 5. Workflow получает signal

В логах:

```
workflow.signal_received signal_name=hitl_approve action=approve
```

Статус инстанса через admin-API:

```bash
curl -s http://localhost:8000/api/v1/admin/workflows/wf-12345
# {"status": "succeeded", ...}
```

Статуса `completed` в системе нет: успешный статус называется
`succeeded`, полный список — в
[Workflows → Схема состояний](../workflows/index.md#схема-состояний).

Разбор и отладка — в разделе
[Workflows → Как отладить](../workflows/index.md#как-отладить).

## What's next?

* Runbook `hitl-stuck-workflow.md` — что делать, если workflow висит.
* Tutorial 11 — ClickHouse audit sink (логирование HITL решений).
