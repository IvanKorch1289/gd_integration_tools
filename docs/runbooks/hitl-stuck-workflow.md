# Runbook: HITL stuck workflow

> Owner: K3.

## Symptom

* Workflow висит в `wait_for_signal` дольше ожидаемого (часы / дни).
* HITL panel показывает старые pending signals.
* Operator не получил notification.

## Detection

```bash
curl http://<api>/api/v1/hitl/pending?tenant_id=<tid>
# items[].created_at >> 24h ago
```

## Diagnosis

1. **Stuck потому что workflow timeout = бесконечность.**
   * Не задан `timeout_s` в `wait_for_signal`.
   * Solution: ставить default timeout 24h (см. tutorial 05).

2. **Operator не видит pending signal.**
   * `feature_flag.hitl_panel_enabled == False`.
   * Tenant filter скрывает signal.
   * Solution: проверить feature-flag + filter.

3. **Notification не дошёл до operator.**
   * Email/Slack escalation не настроен в SLA policy.
   * `SlaTracker.start()` не запущен в lifespan.

## Mitigation

### Manual signal через REST
```bash
curl -X POST http://<api>/api/v1/hitl/<signal_id>/resolve \
  -d '{
    "action": "approve",
    "resolved_by": "ops-admin",
    "comment": "Manual escalation: original operator unavailable"
  }'
```

### Cancel workflow (если approval не возможен)
```bash
curl -X POST http://<api>/api/v1/admin/workflows/<wf_id>/cancel
```

### Bulk discovery старых signals
```python
# Streamlit pages/72_HITL_Panel — фильтр "Older than X days"
# или CLI:
.venv/bin/python -c "
from src.backend.services.workflows.hitl_service import HitlService
svc = ...
old = [s for s in await svc.list_pending() if (now - s.created_at).days > 7]
"
```

## Verification

* Workflow завершается (статус `completed`).
* Pending signal убирается из `list_pending`.
* Audit-event `hitl.signal.resolved` записан.

## Prevention

* Всегда задавать `wait_for_signal(timeout_s=86400)`.
* Настроить SLA policy в `workflow.yaml::sla` (K3 W10).
* Email/Slack escalation в `SlaPolicy` для HITL workflows.

## Postmortem

* Сколько времени signal был pending.
* Original initiator vs final resolver — несоответствие?
* Action: добавить SLA policy с escalation_email.
