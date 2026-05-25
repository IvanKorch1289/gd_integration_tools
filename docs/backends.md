# Multi-Backend Tier Classification (ADR-NEW-11)

> **Status**: ✅ Accepted (S18 W15, 2026-05-25).
> **Source**: PLAN.md V22 §S18 W15 (ADR-NEW-11 / B-2).

## Контекст

gd_integration_tools поддерживает множественные backends для каждого слоя
интеграционной шины (DB / MQ / Storage). Тестировать **все** backends под
chaos + perf-gate в CI экономически нецелесообразно. ADR-NEW-11 вводит
явную **двухтиерную классификацию**: Tier-A (full CI) vs Tier-B (smoke only).

## Tier классификация

### Database

| Backend | Tier | Обоснование |
|---------|------|-------------|
| PostgreSQL | A | Primary OLTP; full RLS + chaos + perf-gate. |
| Oracle | A | Banking-critical legacy; chaos + integration. |
| MSSQL | B | Smoke only; используется редко. |
| MySQL | B | Smoke only; legacy migrations. |
| DB2 | B | Smoke only; банковский mainframe integration. |

### Message Queue

| Backend | Tier | Обоснование |
|---------|------|-------------|
| RabbitMQ | A | Primary MQ; FastStream integration + chaos + perf. |
| Kafka | A | Event streaming; OutboxEventBus + chaos. |
| Redis Streams | B | Smoke only; нишевый use case. |
| NATS JetStream | B | Smoke only; альтернатива для green-field. |

### Object Storage

| Backend | Tier | Обоснование |
|---------|------|-------------|
| AWS S3 | A | Primary; full chaos (region failover) + perf. |
| MinIO | A | On-prem S3-API alternative; chaos + integration. |
| LocalFS | B | Smoke only; dev_light + plugin sandbox. |

## CI matrix (Tier-A)

| Test type | Frequency | Backends |
|-----------|-----------|----------|
| Integration | per-PR | PG, Oracle, RabbitMQ, Kafka, S3, MinIO |
| Chaos (toxiproxy) | nightly | PG, RabbitMQ, S3 (kill replica scenarios) |
| Perf-gate (k6+locust) | weekly | PG (p95 ≤ 80ms), RabbitMQ (RPS ≥ 1500) |

## CI matrix (Tier-B)

| Test type | Frequency | Backends |
|-----------|-----------|----------|
| Smoke | per-PR (5 min budget) | All Tier-B backends |
| Integration | manual / on-demand | На случай регрессии |

Перенос backend из Tier-B → Tier-A триггерится:
- бизнес-заказчик подписывает SLA с этим backend;
- статистика показывает >20% production traffic;
- compliance-аудит требует full chaos coverage.

## Carryover (S18 W15)

- **pyproject.toml extras restructure** (`db-tier-a`, `db-tier-b`,
  `mq-tier-a`, `mq-tier-b`, `storage-tier-a`, `storage-tier-b`) — отдельная
  wave, требует регрессии install-paths + CI matrix update + docs update.
- **CI matrix split в .github/workflows/** — отдельная wave (touch
  ci-config, требует team-review).
- **Pruning Tier-B integration tests** из per-PR в on-demand — отдельная
  wave (требует tag-based test selection + scheduled job).

## Связанные ADR

- ADR-NEW-6 (Tier-A trust для plugins, аналогичный pattern).
- ADR-NEW-12 (RLS Postgres — Tier-A DB primary).
- ADR-NEW-14 (Workflow State Persistence — SQLite Tier-A для in-process).
