# Runbook: ClickHouse bulk writer flush tuning

> Owner: K2.

## Symptom

* `clickhouse_bulk_writer.flush_failures` метрика растёт.
* Audit-events запаздывают (latency > 5s).
* ClickHouse server: high write-amplification, MergeTree много мелких частей.

## Detection

```bash
curl http://<api>/api/v1/admin/audit/stats | jq
# {"rows_flushed": 12345, "flush_count": 24, "flush_failures": 0, ...}
```

ClickHouse:
```sql
SELECT count() FROM system.parts WHERE table = 'audit_events' AND active = 1;
-- если > 10000 — too many parts
```

## Diagnosis

Конфигурация writer'а (`clickhouse_bulk_writer.py`):
* `max_buffer_size` (default 1000) — flush при достижении.
* `flush_interval_seconds` (default 1.0) — timer-flush.
* `queue_max_size` (default 10000) — backpressure порог.

## Mitigation

### Slow consumer (CH перегружен)
```python
# Увеличить buffer + интервал — fewer, bigger inserts
writer = ClickHouseBulkWriter(
    client=ch_client,
    table="audit_events",
    max_buffer_size=10000,
    flush_interval_seconds=5.0,
)
```

### Too many parts (>10k)
```sql
-- Force merge:
OPTIMIZE TABLE audit_events FINAL;
```
Не делать в production без maintenance window.

### Backpressure (queue full)
`add()` блокирует. Решения:
* увеличить `queue_max_size=50000`;
* dedicate writer per shard (per tenant_id);
* добавить fallback в DLQ при `asyncio.QueueFull`.

## Verification

* `flush_failures == 0` за 24h.
* CH `system.parts` count < 5000 per table.
* `rows_flushed / second` стабильно ≥ 5000 (DoD ≥10x).

## Tuning recipe

| Volume | max_buffer | flush_interval | queue_max |
|---|---|---|---|
| < 100 rps | 100 | 5.0s | 1000 |
| 100-1000 rps | 1000 | 1.0s | 10000 |
| 1000-10000 rps | 10000 | 1.0s | 100000 |
| > 10000 rps | 50000 | 0.5s | 500000 |

## Performance check

```bash
make perf-bench-clickhouse
# Per-row: 800 rows/s
# Bulk:    12000 rows/s (15x improvement)
```
