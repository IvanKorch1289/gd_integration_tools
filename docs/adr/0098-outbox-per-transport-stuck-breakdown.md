# ADR-0098: Outbox per-transport stuck breakdown (defer implementation)

**Date:** 2026-06-08
**Status:** Accepted (S75 W2 — design + defer, S68 W2 backlog)
**Sprint:** S75
**Deciders:** core/messaging team
**Supersedes:** — (extends S68 W1, S72 W2, S73 W1)
**Related:** ADR-0051, outbox.py, stuck_monitor.py

## Context

S72 W2 добавил `outbox_stuck_pending_count` gauge (single counter,
all-transport aggregate). S73 W1 добавил Grafana alert rules. S75 W1
добавил Streamlit page.

**Open question**: при alert firing невозможно понять **какой transport**
(Kafka/RabbitMQ/NATS/ClickHouse-house/S3-direct) застрял. Все stuck
messages лежат в одной Postgres таблице с разными `topic` строками,
но Prometheus metric агрегирует их в single value.

Audit проведён 2026-06-08 — current state:

**OutboxMessage model** (infrastructure/database/models/outbox.py):
* `topic: str` — single string field (NOT enum / NOT transport)
* `payload: dict` — JSON content
* `status: str` — pending/sent/failed

**Current stuck query** (infrastructure/repositories/outbox.py:80+):
```sql
SELECT COUNT(*) FROM outbox_messages
WHERE status = 'pending'
  AND created_at < now() - threshold_seconds
  AND retry_count = 0
```

**No `transport` field** in schema. Stuck count is **aggregate-only**.

## Decision

**DEFER** per-transport breakdown implementation. Out of scope для
S75 W2 (limited bandwidth, требует schema migration).

### Design (когда ready to implement)

**Schema addition**:
```python
# infrastructure/database/models/outbox.py
class OutboxMessage(BaseModel):
    __tablename__ = "outbox_messages"
    # ... existing fields ...
    transport: Mapped[str] = mapped_column(String(32), index=True)
    # Values: "kafka" | "rabbitmq" | "nats" | "clickhouse" | "s3" | "webhook" | "other"
```

**Migration**: new column with `default="other"` (backwards-compatible).
Existing rows get `"other"`. New writes set explicit transport from
caller (action metadata).

**Repository extension**:
```python
# infrastructure/repositories/outbox.py
async def count_stuck_pending_by_transport(
    *, threshold_seconds: int
) -> dict[str, int]:
    """Returns {transport: stuck_count} для всех transports."""
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_seconds)
    async with main_session_manager.create_session() as session:
        stmt = (
            select(OutboxMessage.transport, func.count())
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
            .group_by(OutboxMessage.transport)
        )
        result = await session.execute(stmt)
        return {transport: int(count) for transport, count in result.all()}
```

**Metric change**:
```python
# infrastructure/messaging/outbox/stuck_monitor.py
try:
    from prometheus_client import Gauge as _PromGauge
    _STUCK_PENDING_GAUGE = _PromGauge(
        "outbox_stuck_pending_count",
        "Stuck-pending count by transport (worker not picking up)",
        ("transport",),  # NEW label
    )
except Exception:
    _STUCK_PENDING_GAUGE = None

async def _sample_once(self) -> int:
    by_transport = await count_stuck_pending_by_transport(
        threshold_seconds=self._threshold
    )
    if _STUCK_PENDING_GAUGE is not None:
        for transport, count in by_transport.items():
            _STUCK_PENDING_GAUGE.labels(transport=transport).set(count)
    return sum(by_transport.values())
```

**Grafana dashboard update** (outbox_stuck_pending.json):
* Main panel: `sum by (transport) (outbox_stuck_pending_count)` →
  stacked bar / time-series per transport
* Alert rules: per-transport thresholds (e.g. Kafka > 0 vs S3 > 0)

**High-cardinality protection** (S68 noted):
* Без явного `transport` enum (free-form string) → 10K+ labels
  → Prometheus OOM. Mitigation: enum + validation at write time
  (in OutboxBackend.enqueue).

## Consequences

### Positive (when implemented)

* Per-transport alerting: Kafka stuck ≠ S3 stuck (different runbooks)
* Faster root cause: dashboard сразу показывает "Kafka partition X"
  vs "S3 credentials expired"
* Per-tenant × per-transport: S72 W1 already has tenant_id label,
  can combine с transport для full breakdown

### Negative (when implemented)

* Schema migration (new column, backfill default)
* Existing outbox rows (millions?) need backfill
* Cardinality: 10 transports × 10K tenants = 100K label combinations
  (potential Prometheus OOM, need sampling)

### Neutral

* 6 transport types достаточно для текущего scope (kafka/rabbit/nats/ch/s3/webhook)
* Default `"other"` для backward compat

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `OutboxMessage.transport` column | TODO | infrastructure/database/models/outbox.py |
| Migration: add column + backfill | TODO | migrations/versions/ |
| `count_stuck_pending_by_transport` | TODO | infrastructure/repositories/outbox.py |
| `OutboxBackend.enqueue(transport=...)` validation | TODO | core/messaging/outbox.py |
| Per-transport gauge label | TODO | infrastructure/messaging/outbox/stuck_monitor.py |
| Grafana dashboard per-transport panels | TODO | observability/grafana/outbox_stuck_pending.json |
| Per-transport alert rules | TODO | observability/grafana/outbox_stuck_pending_alert.json |
| High-cardinality protection (sampling) | TODO | observability/ |
| Streamlit page per-transport section | TODO | frontend/streamlit_app/pages/96_Outbox_Stuck_Monitor.py |

## Why DEFER (not implement now)

Sprint 36 rule "honest scope reduction":
* Schema migration требует careful rollout (downtime? dual-write?)
* Cardinality analysis нужен (10K tenants × 10 transports = 100K)
* Backfill script для existing rows (separate W)
* Test coverage для edge cases (failed migration, partial backfill)

W2 в S75 = ADR + design, NOT code. Implementation отложен до S76+
когда будет bandwidth для schema work.

## References

* `src/backend/infrastructure/repositories/outbox.py` (count_stuck_pending — existing)
* `src/backend/infrastructure/database/models/outbox.py` (OutboxMessage — no transport field)
* `src/backend/infrastructure/messaging/outbox/stuck_monitor.py` (S72 W2 — single gauge)
* `src/backend/infrastructure/observability/grafana/outbox_stuck_pending.json` (S73 W1)
* `src/backend/infrastructure/observability/grafana/outbox_stuck_pending_alert.json` (S73 W1)
* `src/backend/frontend/streamlit_app/pages/96_Outbox_Stuck_Monitor.py` (S75 W1)
* S68 W1 + S72 W2 + S73 W1 + S75 W1: full observability chain
