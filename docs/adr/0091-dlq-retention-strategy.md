# ADR-0091: DLQ retention strategy (formalize existing unified implementation)

**Date:** 2026-06-08
**Status:** Accepted (S67 W2 — formalize decision, S64 W2 backlog)
**Sprint:** S67
**Deciders:** core/messaging team
**Supersedes:** — (formalizes existing S13 K3 W4 implementation)
**Related:** ADR-0051, dlq_base.py, dlq_policy.py

## Context

Backlog S64-W2: "DLQ retention unified" (от роевого анализа V22).
Подразумевалось что retention настроен per-transport ad-hoc, без
единой policy/janitor.

Audit проведён 2026-06-08 — **DLQ retention ALREADY UNIFIED**:

**Components (verified wc -l):**
```
src/backend/core/messaging/dlq.py                  38 LOC  (DLQ Protocol/types)
src/backend/core/messaging/dlq_policy.py          106 LOC  (DLQPolicy + Registry)
src/backend/infrastructure/messaging/dlq_base.py  114 LOC  (DLQEnvelope + DLQWriter)
src/backend/infrastructure/messaging/dlq/cleanup_job.py   121 LOC  (janitor)
src/backend/infrastructure/messaging/dlq/policy_resolver.py 60 LOC (resolver)
Total:                                              439 LOC
```

**Policy classes (S13 K3 W4):**
* `financial` — 7 лет (2555 дней), unlimited replays
* `analytics` — 30 дней, 3 replays max
* `operational` — 90 дней, 10 replays max (default)

**Routing:**
1. Explicit `route.toml::[dlq] dlq_class = "financial"`
2. `dispatch_action` mapping (category=financial → "financial")
3. Default — "operational"

**Cleanup job (cleanup_job.py):**
* Запускается через APScheduler / TaskRegistry
* Scan DLQ table, delete where `created_at + retention_days < now()` per `dlq_class`
* Metrics: `dlq_cleanup_deleted_total{class}` (Prometheus Counter)
* Per-class statistics + errors tracking

## Decision

**Признать** DLQ retention **PRODUCTION-READY и UNIFIED**.
Реализация S13 K3 W4 закрыта, public API стабилен.

**Не требуется**:
* Migration per-transport (уже unified через `dlq_class`)
* New janitor (уже есть `DLQCleanupJob`)
* Per-transport TTL config (уже через policy classes)

**Already wired**:
* 6 writers (InMemory, Kafka, Rabbit, NATS, Inbox, Fanout) — все совместимы с `DLQWriter` Protocol
* `dlq_replay.yaml` blueprint (dsl/blueprints/) — declarative replay flow
* `admin_scheduler_dlq.py` — admin endpoint
* Grafana dashboards: `dlq_per_transport.json`, `outbox_dlq_depth.json`
* Redis cluster script: `dlq_replay_dedup.lua`

## Consequences

### Positive

* Compliance-ready: financial retention 7 лет (регуляторное требование банка)
* Automatic cleanup — нет ручного управления TTL
* Per-class metrics + alerts (Grafana dashboards готовы)
* Declarative routing через route.toml — operators могут override

### Negative

* Retention_days hardcoded в `DLQPolicy` dataclass — НЕ configurable per-route
  (если нужно per-route — нужна миграция на per-route policy override)
* Default 90 дней (operational) может быть мало для long-running investigations
* Нет auto-archive to cold storage (S3 Glacier etc.) — все удаляется

### Neutral

* 439 LOC distributed across 5 files — clear separation of concerns
* Cleanup job requires APScheduler/TaskRegistry — wiring в bootstrap

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `DLQPolicy` dataclass | DONE | core/messaging/dlq_policy.py:36+ |
| `DLQPolicyRegistry` | DONE | core/messaging/dlq_policy.py:80+ |
| 3 policy classes (financial/analytics/operational) | DONE | core/messaging/dlq_policy.py:53+ |
| `DLQCleanupJob` janitor | DONE | infrastructure/messaging/dlq/cleanup_job.py |
| `policy_resolver` (route.toml → dlq_class) | DONE | infrastructure/messaging/dlq/policy_resolver.py |
| 6 DLQ writers (InMemory/Kafka/Rabbit/NATS/Inbox/Fanout) | DONE | infrastructure/messaging/dlq/*.py |
| `dlq_replay.yaml` blueprint | DONE | dsl/blueprints/dlq_replay.yaml |
| `admin_scheduler_dlq.py` endpoint | DONE | entrypoints/api/v1/endpoints/admin_scheduler_dlq.py |
| Grafana dashboards (2) | DONE | observability/grafana/{dlq_per_transport,outbox_dlq_depth}.json |
| Redis dedup script | DONE | cache/redis_cluster_scripts/dlq_replay_dedup.lua |
| Prometheus metric `dlq_cleanup_deleted_total` | DONE | cleanup_job.py:28+ |
| Per-route retention override | TODO | out of scope |
| Auto-archive to cold storage (S3) | TODO | out of scope |
| DLQ admin UI page (Streamlit) | TODO | out of scope |

## References

* `src/backend/core/messaging/dlq.py` (38 LOC)
* `src/backend/core/messaging/dlq_policy.py` (106 LOC)
* `src/backend/infrastructure/messaging/dlq_base.py` (114 LOC)
* `src/backend/infrastructure/messaging/dlq/cleanup_job.py` (121 LOC)
* `src/backend/infrastructure/messaging/dlq/policy_resolver.py` (60 LOC)
* `src/backend/dsl/blueprints/dlq_replay.yaml`
* `src/backend/entrypoints/api/v1/endpoints/admin_scheduler_dlq.py`
* `src/backend/infrastructure/observability/grafana/dlq_per_transport.json`
* S13 K3 W4: original implementation sprint
* ADR-0051 (parent: in-house DLQ, not Kafka/Rabbit native)
