# Runbook: DLQ replay

> Owner: K2. Symptom→Diagnosis→Mitigation→Verification.

> **Scope: messaging.** Этот runbook — про DLQ транспортов
> (Kafka/RabbitMQ/NATS/Inbox, admin-API `/api/v1/admin/dlq/*`, метрика
> `dlq_depth` по транспортам).
>
> **Workflow-шаги в этот DLQ не попадают** (ADR-0403): `workflow_events` —
> append-only event log инстанса, а не очередь недоставленных сообщений.
> Исчерпание retry-бюджета шага даёт терминальный `FAILED` + метрику +
> запись об ошибке в `workflow_instances.error`; переигровки шага не
> существует. Если workflow завис — см. runbook
> [HITL stuck workflow](hitl-stuck-workflow.md).

## Symptom

* Grafana alert `dlq_depth > 200` (per-transport) долго не падает.
* Sentry: всплеск `httpx.ConnectTimeout` / `WAFBlocked`.
* User-reports о пропавших сообщениях / failed callbacks.

## Detection

```bash
curl -s http://<api>/api/v1/admin/dlq/stats | jq
# {"http": 230, "soap": 5, "grpc": 0, "webhook": 12, "total": 247}
```

## Diagnosis

1. **Reason breakdown**: см. Grafana piechart `dlq_per_transport`.
   * Если 90% `timeout` → upstream off, не replay'им до восстановления.
   * Если 90% `validation_failed` → плагин/route bug; найди commit
     через trace_id.
   * Если `capability_denied` → новый capability не задекларирован.

2. **Trace одного envelope**:
   ```bash
   curl http://<api>/api/v1/admin/dlq/<dlq_id> | jq .trace_id
   # → открыть Jaeger
   ```

## Mitigation

### Single message
```bash
curl -X POST http://<api>/api/v1/admin/dlq/<dlq_id>/replay
```

### Batch (по reason + transport)
```bash
curl -X POST http://<api>/api/v1/admin/dlq/batch-replay \
  -d '{"reason": "timeout", "transport": "http", "limit": 100}'
```

### Polish: rate-limited replay
Если DLQ depth >1000, batch-replay с rate 50/s через Granian:

```bash
for batch in $(seq 1 20); do
  curl -X POST .../batch-replay -d '{"limit": 50}'
  sleep 1
done
```

## Verification

* Grafana `dlq_depth{transport=...}` падает.
* Sentry новых ошибок не приходит.
* `dlq_replay_success_total` метрика растёт.

## Rollback

Если replay усугубил ситуацию (cascading failures на upstream):

1. Stop batch replay (cancel curl loop).
2. Force-discard оставшиеся envelopes (admin operation):
   ```bash
   curl -X POST .../dlq/discard -d '{"reason": "timeout", "before": "<ts>"}'
   ```
3. Investigate upstream → fix → resume.

## Postmortem

Стандартный template (`incident-response.md`). Обязательно зафиксировать:
* trace_id первого failure;
* upstream component + version;
* mitigation timeline.
