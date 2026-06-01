# Tutorial 04 — Temporal workflow с XOR/AND gateways

> **Prerequisites:** Tutorial 02 (first plugin). Temporal сервер запущен.
> ~45 минут.

## Цель

Создать workflow с branch-логикой через WorkflowBuilder fluent API,
зарегистрировать его в Temporal worker, запустить из REST endpoint.

## Шаги

### 1. Декларация workflow в Python

```python
from src.backend.dsl.workflow.builder import WorkflowBuilder

wf = (
    WorkflowBuilder("credit_decision")
    .default_timeout(120.0)
    .activity("fetch_credit_score", args={"applicant_id": "${input.id}"})
    .gateway_xor(
        BranchSpec(
            condition="score >= 700",
            steps=[Activity("approve_loan")],
        ),
        BranchSpec(
            condition="score < 700",
            steps=[Activity("reject_loan")],
        ),
    )
    .activity("send_notification")
    .build()
)
```

### 2. Альтернативно — YAML

```yaml
name: credit_decision
version: "1.0"
default_timeout_s: 120
steps:
  - activity: fetch_credit_score
    args: {applicant_id: ${input.id}}
  - gateway_xor:
      branches:
        - condition: "score >= 700"
          steps: [activity: approve_loan]
        - condition: "score < 700"
          steps: [activity: reject_loan]
  - activity: send_notification
```

### 3. Регистрация в Worker

```python
from src.backend.infrastructure.workflow.temporal_client import (
    TemporalClientFactory, TemporalWorkerPool,
)

factory = TemporalClientFactory(target_host="localhost:7233")
pool = TemporalWorkerPool(factory=factory, namespace="default")
await pool.register_worker(
    task_queue="credit-queue",
    workflows=[CreditDecisionWorkflow],
    activities=[fetch_credit_score, approve_loan, reject_loan, send_notification],
)
```

### 4. Запуск из REST

```bash
curl -X POST http://localhost:8000/api/v1/invocations \
  -H "Content-Type: application/json" \
  -d '{"workflow": "credit_decision", "input": {"id": "applicant-42"}, "mode": "async-api"}'
# {"invocation_id": "wf-12345"}
```

### 5. Проверить результат

```bash
curl http://localhost:8000/api/v1/invocations/wf-12345
# {"status": "completed", "result": {"decision": "approved"}}
```

## What's next?

* Tutorial 05 — HITL workflow с wait_for_signal.
* Tutorial 11 — ClickHouse audit sink.
* Workflow SLA alerting (см. K3 W10).
