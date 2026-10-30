# Runbook: HITL stuck workflow

> Owner: K3 DSL+Workflow.

Термины: **шаг** (step) — одна декларация в `steps[]`; **этап** (stage) —
крупная фаза из нескольких шагов. В этом runbook речь о шаге
`wait_signal` (тип `wait_signal` в YAML, `wait_for_signal(...)` в
Python-builder).

## Symptom

* Workflow висит в ожидании сигнала (`wait_signal`) дольше ожидаемого
  (часы / дни).
* HITL panel показывает старые pending signals.
* Operator не получил notification.

## Detection

```bash
curl "http://<api>/api/v1/hitl/pending?tenant_id=<tid>"
# items[].created_at >> 24h ago
```

Статус инстанса workflow — admin-API:

```bash
curl "http://<api>/api/v1/admin/workflows/<wf_id>"
# "status": "paused"
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

3. **Notification не дошёл до operator.**
   * Email/Slack escalation в SLA-политике не настроен.
   * **SlaTracker не запущен — и это не баг конфигурации, а
     нереализованная возможность: SLA-алертинг не реализовано.** Класс
     `SlaTracker`
     (`src/backend/services/workflows/sla_alerting.py`) существует, но
     **не инстанцируется нигде в `src/`**: ни в `lifespan`, ни в
     worker'ах, ни в composition root. `WorkflowFacade` принимает
     `sla_tracker` только как опциональный параметр, а сам фасад в `src/`
     не создаётся. Поэтому автоматической эскалации по SLA в рантайме нет
     вовсе — настраивать «SLA-политику» для workflow бессмысленно, пока
     не появится исполнитель. Следите за owner-задачей, а не за
     конфигурацией.
   * Owner-задача: K3 DSL+Workflow, **GAP-WF-4.5** — зафиксирована в
     [PROD_READINESS_GAPS.md](../roadmap/PROD_READINESS_GAPS.md), сводка —
     в [OWNER_TASKS.md](../roadmap/OWNER_TASKS.md) § 8.

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

> **Не реализовано:** audit-event `hitl.signal.resolved` в отдельном
> audit-sink не пишется. Step-level audit-события по шагам workflow
> вообще не эмится: `StepAuditMiddleware`
> (`src/backend/infrastructure/workflow/middlewares/step_audit.py`)
> существует, но не инстанцируется и не подключён к runner'у (см.
> «Не реализовано» в [Workflows](../workflows/index.md#не-реализовано)).
> Не стройте детекцию на «audit → ClickHouse».

## Prevention

* Всегда задавать `wait_for_signal(timeout_s=86400)`.
* Настроить SLA-политику в декларации workflow (`sla:` в
  `WorkflowDeclaration` / `.sla(...)` в builder) — но помните, что
  **исполнителя SLA-трекера не существует**: `SlaTracker` не
  инстанцируется нигде в `src/` (см. диагностику п. 3, owner-задача
  GAP-WF-4.5).
* Эскалацию по SLA (email/Slack) в `SlaPolicy` пока не рассчитывайте
  как работающую — это owner-задача K3.

## Postmortem

* Сколько времени signal был pending.
* Original initiator vs final resolver — несоответствие?
* Action: добавить SLA policy с escalation_email **после** появления
  исполнителя SLA-трекера.
