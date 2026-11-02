# Runbook: HITL stuck workflow

> Owner: K3 DSL+Workflow.

Термины: **шаг** (step) — одна декларация в `steps[]`; **этап** (stage) —
крупная фаза из нескольких шагов. В этом runbook речь о шаге
`wait_signal` (тип `wait_signal` в YAML, `wait_for_signal(...)` в
Python-builder).

Фактическая семантика волны 22 (ADR-0408): исчерпание retry-бюджета
шага → **терминальный `failed`** + **запись шага в DLQ** (transport
`workflow`) + **метрика** `workflow_sla_compliance_total{level}` +
alert-рул (`docs/ops/workflow-sla-alerts.md`).

## Symptom

* Workflow висит в ожидании сигнала (`wait_signal`) дольше ожидаемого
  (часы / дни).
* HITL panel показывает старые pending signals.
* Operator не получил notification.
* Workflow упал после исчерпания попыток шага: в admin-API
  `"status": "failed"`, в `workflow_instances.error` — `max_attempts
  exceeded (N/N)`, в DLQ — запись с `transport="workflow"`.

## Detection

```bash
curl "http://<api>/api/v1/hitl/pending?tenant_id=<tid>"
# items[].created_at >> 24h ago
```

Статус инстанса workflow — admin-API:

```bash
curl "http://<api>/api/v1/admin/workflows/<wf_id>"
# "status": "paused"  (ждём сигнала)  |  "status": "failed" (бюджет исчерпан)
```

Исчерпанные шаги в DLQ (transport `workflow`):

```bash
curl -s "http://<api>/api/v1/admin/dlq?transport=workflow"
# transport=workflow, reason=retries_exhausted, metadata.step=<имя шага>
```

Метрики SLA и DLQ:

```bash
curl -s http://<api>/metrics | grep -E "workflow_sla_compliance_total|workflow_dlq_publish_total"
# workflow_sla_compliance_total{level="hard"} 3.0   — нарушения бюджета
# workflow_dlq_publish_total{status="published"} 3.0 — ушло в DLQ
```

## Diagnosis

1. **Workflow завис, потому что у шага ожидания нет таймаута.**
   * Не задан `timeout_s` в `wait_signal` / `wait_for_signal(...)`.
   * Solution: ставить default timeout 24h (см. tutorial 05).

2. **Operator не видит pending signal.**
   * Feature-flag `feature_flags.hitl_panel_enabled` выключен в профиле.
     Дефолт флага — **True** (`core/config/features/infrastructure.py`),
     то есть «выключен» — это явная настройка профиля, а не дефолт.
   * Tenant filter скрывает signal (`tenant_id` в `GET /hitl/pending`).
   * Solution: проверить feature-flag + filter.

3. **Workflow упал по исчерпанию попыток.**
   * `error` в admin-API: `max_attempts exceeded (3/3): <причина>`.
   * Шаг не дошёл до конца: попытки кончились (`max_attempts` из спеки
     workflow'а / `RetryPolicy`).
   * Что произошло: шаг перешёл в **терминальный `failed`**, компенсации
     выполненных forward-шагов запущены (ADR-0396), сам исчерпанный шаг
     попал в **DLQ** (transport `workflow`, `reason=retries_exhausted`),
     инкрементнулся счётчик `workflow_dlq_publish_total{status="published"}`.
   * Запись идемпотентна: повторный запуск того же шага не создаёт
     второй записи (детерминированный `dlq_id`).
   * Solution: разобрать запись в DLQ (`metadata.step`, `metadata.attempts`,
     `error_message`), починить первопричину и перезапустить workflow.

4. **Notification не дошёл до operator.**
   * Уведомление о нарушении SLA приходит **алертом Prometheus**
     (`workflow_sla_compliance_total` + правила из
     [workflow-sla-alerts.md](../ops/workflow-sla-alerts.md)), а не
     письмом/Slack: **канала эскалации (email/Slack) в репозитории нет**,
     поэтому «SLA-алертинг» = метрика + alert-рул (ADR-0408).
   * Класс `SlaTracker` и протокол `SlaAlertDispatcher` удалены как
     мёртвый код (ADR-0403) и не возвращались: оценка SLA выполняется
     в точке терминального перехода workflow'а, фоновый трекер не нужен.
   * `WorkflowFacade` (который умеет брать SLA hard-limit как бюджет
     времени) по-прежнему не создаётся в `src/`: production-путь старта
     workflow идёт напрямую через `WorkflowBackend`
     (`dsl/engine/processors/invoke_workflow.py`) — это отдельная
     owner-задача K3 DSL+Workflow.
   * Owner-задачи: K3 DSL+Workflow — **GAP-WF-4.5** закрыт кодом
     (ADR-0408: метрика + alert-рул); остаточные пункты (подключение
     фасада, доставка alert-рула в Prometheus, реестр owner-задач) —
     в [PROD_READINESS_GAPS.md](../roadmap/PROD_READINESS_GAPS.md),
     сводка — в [OWNER_TASKS.md](../roadmap/OWNER_TASKS.md) § 8,
     решение волны 21 — в
     [ADR-0403](../adr/0403-workflow-sla-dlq-and-prod-validator.md),
     волны 22 — в
     [ADR-0408](../adr/0408-workflow-dlq-contract-and-sla-alerting.md).

## Mitigation

### Manual signal через REST

```bash
curl -X POST "http://<api>/api/v1/hitl/<signal_id>/resolve" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "approve",
    "resolved_by": "ops-admin",
    "comment": "Manual escalation: original operator unavailable"
  }'
```

### Cancel workflow (если approval не возможен)

```bash
curl -X POST "http://<api>/api/v1/admin/workflows/<wf_id>/cancel" \
  -H "Content-Type: application/json" \
  -d '{"reason": "operator escalation: original approver unavailable"}'
```

### Возобновить paused workflow

```bash
curl -X POST "http://<api>/api/v1/admin/workflows/<wf_id>/resume"
```

### Разобрать исчерпанный шаг из DLQ

```bash
curl -s "http://<api>/api/v1/admin/dlq?transport=workflow" | jq '.[].metadata'
# {"workflow_id": "...", "step": "charge_card", "attempts": 3,
#  "max_attempts": 3, "reason": "max_attempts_exceeded", "payload_keys": [...]}
```

Значения данных workflow в DLQ-записи нет — только метаданные шага
(`payload_keys` — имена ключей). Для разбора используйте event log
инстанта и входной payload workflow'а.

### Переиграть исчерпанный шаг (DLQ-replay)

После починки первопричины исчерпанный шаг можно переиграть: DLQ-replay
сбрасывает retry-бюджет инстанса и возвращает его в `pending`
(ADR-0408).

```python
import json

from src.backend.infrastructure.workflow.pg_runner_backend import (
    PgRunnerWorkflowBackend,
)

record = {"workflow_id": "<uuid>", "step": "charge_card", "attempts": 3}
backend = PgRunnerWorkflowBackend()
await backend.replay(
    workflow_name="orders.saga",
    history=json.dumps(record).encode(),
)
```

Ошибки: нечитаемая запись → `ValueError`, неизвестный инстанс →
`KeyError`, терминальный статус (`succeeded`/`cancelled`) → `ValueError`
(переигровывать нечего).

### Bulk discovery старых signals

```python
# Streamlit pages/72_HITL_Panel — фильтр "Older than X days"
# или напрямую через сервис:
from src.backend.services.workflows.hitl_service import (
    HitlService,
    InMemoryHitlSignalStore,
)

svc = HitlService(store=InMemoryHitlSignalStore())
old = [s for s in await svc.list_pending() if (now - s.created_at).days > 7]
```

## Verification

* Workflow выходит из `paused` и приходит в терминальный статус
  (`succeeded` / `failed` / `cancelled`); статуса `completed` в системе
  нет — полный список в
  [Workflows → Схема состояний](../workflows/index.md#схема-состояний).
* Pending signal убирается из `list_pending`.
* В event log инстанса есть событие `signal_received`
  (`GET /api/v1/admin/workflows/<wf_id>/events`).
* Для упавшего по бюджету шага: в DLQ есть запись `transport=workflow`
  с `metadata.step` и `metadata.attempts`; повторный запуск не создаёт
  вторую запись; `workflow_dlq_publish_total{status="published"}` вырос.
* Для SLA: `workflow_sla_compliance_total{level="hard"}` вырос, если
  бюджет превышен (порог — из настроек SLO роутов, см.
  [workflow-sla-alerts.md](../ops/workflow-sla-alerts.md)).

> **Не эмитится:** audit-event `hitl.signal.resolved` в отдельном
> audit-sink не пишется. Step-level audit-события по шагам workflow
> вообще не эмится: `StepAuditMiddleware`
> (`src/backend/infrastructure/workflow/middlewares/step_audit.py`)
> существует, но не инстанцируется и не подключён к runner'у (см.
> раздел про нереализованные возможности в
> [Workflows](../workflows/index.md#не-реализовано)).
> Не стройте детекцию на «audit → ClickHouse».

## Prevention

* Всегда задавать `wait_for_signal(timeout_s=86400)`.
* Задавать SLA-политику в декларации workflow (`sla:` в
  `WorkflowDeclaration` / `.sla(...)` в builder) — она даёт бюджет
  времени, по которому считается метрика SLA и срабатывает алерт.
  Учтите: escalation по SLA (email/Slack) не работает — канала
  эскалации нет; детекция — по метрике и Prometheus-алерту.
* Держите бюджет времени workflow'а согласованным с SLO роутов
  (`route.toml::slo.timeout_ms`): превышение бюджета — это и есть
  hard-breach в метрике.
* Для шагов с внешними вызовами задавайте разумный `max_attempts`:
  каждый исчерпанный шаг — это запись в DLQ, которую нужно разбирать.

## Postmortem

* Сколько времени signal был pending.
* Original initiator vs final resolver — несоответствие?
* Action: добавить SLA policy с escalation_email **после** появления
  канала эскалации; до этого — следить за alert'ом
  `WorkflowSlaHardBreach`.
