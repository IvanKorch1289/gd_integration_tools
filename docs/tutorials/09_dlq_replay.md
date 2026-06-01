# Tutorial 09 — DLQ debug + replay

> **Prerequisites:** Tutorial 08. ~25 минут.

## Цель

Найти failed message в DLQ, диагностировать причину, переотправить.

## Шаги

### 1. Просмотреть DLQ

В admin UI: `pages/54_DLQ_Replay` → таблица failed messages с
breakdown по transport + reason.

Через CLI:

```bash
curl http://localhost:8000/api/v1/admin/dlq?transport=http&limit=20
```

### 2. Inspect envelope

```bash
curl http://localhost:8000/api/v1/admin/dlq/<dlq_id>
```

Response:

```json
{
  "dlq_id": "uuid-1234",
  "transport": "http",
  "trace_id": "...",
  "tenant_id": "bank-corp",
  "route_id": "credit_check_v2",
  "original_payload": {...},
  "error_class": "httpx.ConnectTimeout",
  "error_message": "timeout to api.example.com",
  "reason": "timeout",
  "retry_count": 3,
  "first_failed_at": "2026-05-19T12:00:00Z"
}
```

### 3. Диагностика через Jaeger

`trace_id` → открыть Jaeger UI → найти trace → инспектировать spans.

### 4. Replay одного сообщения

```bash
curl -X POST http://localhost:8000/api/v1/admin/dlq/<dlq_id>/replay
# {"status": "ok", "replayed_at": "..."}
```

### 5. Batch replay по filter

```bash
curl -X POST http://localhost:8000/api/v1/admin/dlq/batch-replay \
  -d '{"reason": "timeout", "transport": "http", "limit": 100}'
```

### 6. Grafana dashboard

`grafana/dlq_per_transport.json` — 4 stat panels (HTTP/SOAP/gRPC/Webhook),
piechart by reason, top-10 failing routes.

## What's next?

* Runbook `dlq-replay.md` — production playbook.
* DLQ writers: Kafka/Rabbit/NATS/Inbox (см. K2 W1).
* GAP-15 §A-1 — DLQ full integration.
