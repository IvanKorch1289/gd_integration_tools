# Tutorial 11 — ClickHouse bulk writer + audit sink

> **Prerequisites:** ClickHouse запущен. ~30 минут.

## Цель

Настроить ClickHouse bulk writer для audit-events с ≥10x throughput
по сравнению с per-row insert.

## Шаги

### 1. Создать таблицу в ClickHouse

```sql
CREATE TABLE audit_events (
    event_id String,
    tenant_id String,
    event_type String,
    user_id String,
    payload String,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (tenant_id, created_at)
TTL created_at + INTERVAL 90 DAY;
```

### 2. Composition root

```python
# src/backend/plugins/composition/lifecycle.py
from src.backend.infrastructure.clients.storage.clickhouse import (
    ClickHouseClient,
)
from src.backend.infrastructure.clients.storage.clickhouse_bulk_writer import (
    ClickHouseBulkWriter,
)

ch_client = ClickHouseClient(host="clickhouse", database="audit")
audit_writer = ClickHouseBulkWriter(
    client=ch_client,
    table="audit_events",
    max_buffer_size=1000,
    flush_interval_seconds=1.0,
)
await audit_writer.start()
```

### 3. Использование в audit-pipeline

```python
async def emit_audit(event: dict) -> None:
    await audit_writer.add({
        "event_id": str(uuid.uuid4()),
        "tenant_id": event["tenant_id"],
        "event_type": event["type"],
        "user_id": event["user"],
        "payload": json.dumps(event["payload"]),
    })
```

### 4. Graceful shutdown

```python
# lifespan
await audit_writer.aclose()  # flush final buffer
```

### 5. Метрики Prometheus

```python
@router.get("/admin/audit/stats")
def audit_stats():
    return {
        "rows_flushed": audit_writer.stats.rows_flushed,
        "flush_count": audit_writer.stats.flush_count,
        "flush_failures": audit_writer.stats.flush_failures,
    }
```

### 6. Throughput benchmark

```bash
make perf-bench-clickhouse
# Per-row insert: 800 rows/s
# Bulk writer: 12000 rows/s  (15x improvement)
```

## What's next?

* Runbook `clickhouse-flush-tuning.md` — fine-tune buffer/interval.
* GAP-15 — DoD-9 ClickHouse bulk writer ≥10x throughput.
* Grafana dashboard для audit_events monitoring.
