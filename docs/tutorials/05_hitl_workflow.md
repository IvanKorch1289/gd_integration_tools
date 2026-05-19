# Tutorial 05 — HITL workflow с approval signal

> **Prerequisites:** Tutorial 04. ~40 минут.

## Цель

Создать workflow, который ждёт human approval через signal. Operator
видит pending signal в HITL panel (page 72) и approve/reject.

## Шаги

### 1. Декларация workflow с wait_for_signal

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
        args={"action": "${operator_decision.action}"},
    )
    .build()
)
```

### 2. Зарегистрировать pending signal в HitlService

В activity `prepare_application_summary` после подготовки summary:

```python
from src.backend.services.workflows.hitl_service import (
    HitlPendingSignal, HitlService,
)

await hitl_service.register_pending(HitlPendingSignal(
    signal_id=workflow.info().workflow_id,
    workflow_id=workflow.info().workflow_id,
    tenant_id=context.tenant_id,
    signal_name="hitl_approve",
    initiator=context.user_id,
    title=f"Loan review #{application_id}",
    payload={"amount": amount, "score": score, "applicant": applicant_name},
))
```

### 3. Запустить workflow

```bash
curl -X POST http://localhost:8000/api/v1/invocations \
  -H "Content-Type: application/json" \
  -d '{"workflow": "loan_review_hitl", "input": {"app_id": "loan-42"}, "mode": "async"}'
```

### 4. Operator approve через UI

* Открыть `http://localhost:8501` → страница `72_HITL_Panel`.
* Выбрать pending signal (если фильтруется — указать `tenant_id`).
* Заполнить `Operator name` + `Comment`, нажать `Approve`.

### 5. Workflow получает signal

В логах:

```
workflow.signal_received signal_name=hitl_approve action=approve
```

Result через REST:

```bash
curl http://localhost:8000/api/v1/invocations/<wf_id>
# {"status": "completed", "result": {"decision": "approved"}}
```

## What's next?

* Runbook `hitl-stuck-workflow.md` — что делать если workflow висит.
* Tutorial 11 — ClickHouse audit sink (логирование HITL решений).
