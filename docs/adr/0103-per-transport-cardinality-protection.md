# ADR-0103: Per-transport cardinality protection (ND-001 step 8)

**Date:** 2026-06-08
**Status:** Accepted (S81 W4 — formalize, ND-001 step 8)
**Sprint:** S81
**Deciders:** platform team
**Related:** ADR-0098 (S75 W2 defer), ADR-0099 (v28 reconciliation)

## Context

S81 W2-W3 added per-transport gauge label (transport=kafka/s3/etc.).
Prometheus cardinality concern: unbounded label values → memory blowup.

**Example of bad practice** (do NOT do this):
```python
# BAD: cardinality = num_topics * num_tenants
_StuckPendingGauge.labels(transport=topic, tenant_id=tenant_id).set(count)
```

If 1000 topics × 100 tenants = 100,000 time series для 1 metric.
Плюс label-combination explosion с другими labels.

## Decision

**Bound cardinality at write time** via fixed enum `ALLOWED_TRANSPORTS` (S81 W2):

```python
ALLOWED_TRANSPORTS: frozenset[str] = frozenset(
    {"kafka", "rabbitmq", "nats", "clickhouse", "s3", "webhook", "other"}
)
```

**Cardinality = 8** (7 transports + 1 `_aggregate_` sentinel).

## Why this works

| Property | Value | Why |
|----------|-------|-----|
| Allowed values | 7 transports | Fixed set, validated at write time |
| Aggregate sentinel | 1 (`_aggregate_`) | Total across all transports |
| **Total cardinality** | **8** | Bounded, well below Prometheus limits |
| Memory per metric | 8 × (16 bytes label + 8 bytes value) ≈ 200 bytes | Trivial |
| Storage growth | linear in # of distinct transports | Cannot exceed 7 |

## Implementation

1. **S81 W2**: `validate_transport()` rejects unknown values → enforced at API boundary.
2. **S81 W2**: `validate_transport()` lowercases input → no "Kafka" vs "kafka" explosion.
3. **S81 W2**: aggregate gauge uses sentinel `_aggregate_` (not 'all'/'total'/'sum') → no collision.
4. **S81 W3**: Grafana queries filter by `{transport!="_aggregate_"}` → exclude sentinel from per-transport panels.

## Adding a new transport

To add e.g. "kinesis" as new transport:

1. Extend `ALLOWED_TRANSPORTS`:
   ```python
   ALLOWED_TRANSPORTS = frozenset({..., "kinesis"})
   ```
2. Add `OutboxBackend` writer для kinesis (separate ADR).
3. Update Grafana panels (S81 W3 — auto via label_values query).
4. Document в `docs/adr/0103-...md` (this file).

**No cardinality change** for existing transports (8 → still 8 until 8th added).

## Why NOT use more labels

Considered but rejected:
- **transport + tenant_id** (100 tenants × 7 transports = 700) — 87x bloat, не оправдано (tenants обычно shared transports)
- **transport + topic** (1000 topics × 7 = 7000) — 875x bloat, отдельные dashboards с labels
- **transport + version** (5 versions × 7 = 35) — 4x bloat, version из redundancy

Decision: keep cardinality at 8. If future requirements demand per-tenant
или per-topic, add SEPARATE metric (e.g., `outbox_stuck_pending_by_tenant_count`)
with documented cardinality cap.

## Outbox chain status (S68 → S81 closed)

| Step | Status | Sprint |
|------|--------|--------|
| 1. count_stuck_pending() | ✅ | S68 W1 |
| 2. OutboxStuckMonitor (gauge) | ✅ | S72 W2 |
| 3. Grafana dashboard (single) | ✅ | S73 W1 |
| 4. Grafana alert rules (2) | ✅ | S73 W1 |
| 5. Streamlit page 96 (single) | ✅ | S75 W1 |
| 6. ND-002 (page fallback) | ✅ | S80 W2 |
| 7. Schema migration (transport column) | ✅ | S80 W3 |
| 8. Per-transport repository (count_by_transport) | ✅ | S80 W3 |
| 9. validate_transport() | ✅ | S81 W2 |
| 10. Per-transport gauge label | ✅ | S81 W2 |
| 11. Per-transport Grafana panel | ✅ | S81 W3 |
| 12. Per-transport alert rule | ✅ | S81 W3 |
| 13. **Cardinality protection (this ADR)** | ✅ | **S81 W4** |
| 14. Streamlit per-transport section | ✅ | S81 W4 |

All 14 steps closed. ND-001 fully complete.

## References

* `src/backend/infrastructure/repositories/outbox.py` (validate_transport, ALLOWED_TRANSPORTS)
* `src/backend/infrastructure/messaging/outbox/stuck_monitor.py` (per-transport gauge)
* `src/backend/infrastructure/observability/grafana/outbox_stuck_pending.json` (per-transport panel)
* `src/backend/infrastructure/observability/grafana/outbox_stuck_pending_alert.json` (3 rules)
* `src/frontend/streamlit_app/pages/96_Outbox_Stuck_Monitor.py` (per-transport section)
* ADR-0098 (S75 W2 defer), ADR-0099 (S76 W1 v28 reconciliation)
