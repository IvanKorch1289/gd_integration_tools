# Migration: TaskIQ removal (S8 → S9)

> Status: closed in Sprint 8 closure. См. PLAN.md V19.1 §2.5 (S8 BLOCKER #1).

## Rationale

Decision: Temporal полностью покрывает функциональность TaskIQ
(background/deferred/cron + saga/replay/versioning). Stack
упрощается до **FastStream (MQ) + APScheduler (простой scheduling) +
Temporal (durable execution через Workflow DSL)**. Это решение
зафиксировано в `R-V15-7` (CLAUDE.md).

## Scope

Удалены:
* `pyproject.toml::dependencies::taskiq*` (taskiq, taskiq-redis,
  taskiq-aio-pika)
* `services/scheduling/taskiq_*.py`
* `entrypoints/cli/taskiq_worker.py`
* `compose/docker-compose.taskiq.yml`

## Replacement mapping

| TaskIQ feature | Replacement |
|---|---|
| Async task enqueue | Temporal start_workflow или FastStream publish |
| Cron schedule | APScheduler (sync simple jobs) или Temporal cron-schedule |
| Retry / DLQ | Temporal retry policies или infrastructure/messaging/dlq |
| Worker pool | Temporal worker (см. K3 W9) |
| Result store | Temporal workflow result через handle.result() |

## Migration steps для уже использовавших TaskIQ

1. **Identify usages**:
   ```bash
   grep -r "taskiq\|broker.task" extensions/ src/backend/
   ```

2. **Wrap в Temporal activity / workflow**:
   ```python
   # Было:
   @broker.task
   async def send_email(to: str, body: str):
       ...

   # Стало:
   @activity.defn
   async def send_email(to: str, body: str) -> None:
       ...

   @workflow.defn
   class EmailWorkflow:
       @workflow.run
       async def run(self, params: dict) -> None:
           await workflow.execute_activity(
               send_email,
               args=[params["to"], params["body"]],
               start_to_close_timeout=timedelta(seconds=30),
           )
   ```

3. **Schedule через Temporal cron**:
   ```python
   await client.start_workflow(
       EmailWorkflow.run, params,
       id="daily-digest",
       cron_schedule="0 9 * * *",
       task_queue="email-queue",
   )
   ```

4. **Verification**: `make test-e2e` должно проходить + Temporal UI
   показывает запущенные workflows.

## Related

* ADR-0044 — Temporal-as-default backend
* `core/workflow/backend.py` — Protocol
* `services/workflows/facade.py` — capability-gated wrapper
