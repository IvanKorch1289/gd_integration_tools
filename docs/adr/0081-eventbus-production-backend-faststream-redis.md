# ADR-0081 — Event Bus Production Backend: FastStream + Redis

**Status:** Accepted
**Date:** 2026-05-27
**Authors:** К3
**Sources:** S19 K3 W1 (backbone), S18 W7 (EventBus DSL), PLAN.md V22.4 §S19 adr-w2
**Supersedes:** N/A (new ADR; resolves R1.8 open item)

---

## Context

R1.8 (open item from pre-V22 planning for S18 W7 EventBus DSL) posed the question: which message broker should serve as the production backend for the EventBus — **NATS**, **Kafka**, **RabbitMQ**, or **Redis Streams** (via FastStream)?

The EventBus DSL (`event.publish()`, `event.subscribe()`) was introduced in S18 W7 to provide a unified async messaging interface. The production backend decision was deferred from S18 to S19.

Three candidates were evaluated against requirements:
- **Async pub/sub** (not just queues)
- **Schema validation** via `ServiceSchemaRegistry`
- **At-least-once delivery** for audit-critical events
- **Operational simplicity** (team has no dedicated Kafka/NATS ops)
- **Redis compatibility** (already used for caching and session management)

---

## Decision

**Use FastStream with Redis broker (`RedisBroker`) as the primary EventBus backend.**

Implementation in `src/backend/infrastructure/clients/messaging/event_bus.py`:
```python
class EventBus:
    def _create_broker(self) -> RedisBroker:
        from faststream.redis import RedisBroker
        return RedisBroker(redis_url)
```

The `EventBus` class provides:
- `publish(channel, event_type, payload)` — async pub/sub
- `subscribe(channel, handler)` — async subscription with schema validation
- `requestReply(channel, event_type, payload, timeout)` — RPC-style request/reply

---

## Alternatives Evaluated

| Backend | Pub/Sub | Schema Validation | At-Least-Once | Operational Complexity | Decision |
|---------|---------|-----------------|---------------|----------------------|----------|
| **FastStream + Redis** | ✅ (Redis Streams) | ✅ (via ServiceSchemaRegistry) | ✅ (ack-based) | Low (Redis already in stack) | **Selected** |
| NATS | ✅ | ⚠️ (no native JSON Schema) | ✅ | Medium (separate NATS cluster) | Deferred |
| Kafka | ✅ | ⚠️ (Schema Registry separate) | ✅ | High (ZooKeeper/KRaft, partition management) | Rejected |
| RabbitMQ | ✅ (exchange/binding) | ⚠️ (schema-validation plugin) | ✅ | Medium (vhost management) | Rejected |
| Redis Streams (raw) | ✅ | ❌ (manual) | ⚠️ (manual) | Medium (no schema, no DSL) | Rejected (use FastStream instead) |

### NATS Rejection Reason
NATS has superior message persistence and JetStream, but requires a separate operational cluster and has no built-in JSON Schema validation. The team has no NATS expertise, and adding NATS would increase operational surface area significantly.

### Kafka Rejection Reason
Kafka is the standard for high-throughput event streaming, but it requires ZooKeeper or KRaft for cluster management, schema registry (separate service), and partition/replication tuning. Overkill for the current scale (~10k events/day). Can be swapped in via FastStream Kafka support when scale demands.

### RabbitMQ Rejection Reason
RabbitMQ is a good fit for async messaging but the AMQP protocol has higher latency than Redis Streams for short messages, and the operational model (vhosts, exchanges, bindings) is more complex than needed.

---

## Consequences

### Positive

- **Low operational complexity**: Redis is already in the stack for caching and session management
- **FastStream abstraction**: same interface can swap to NATS or Kafka as needed (FastStream supports Redis, RabbitMQ, NATS, Kafka)
- **Schema validation**: `EventBus.publish()` validates against `ServiceSchemaRegistry` before publishing
- **At-least-once delivery**: Redis Streams consumer acknowledgments ensure delivery
- **Minimal latency**: Redis pub/sub has sub-millisecond latency for in-memory messages

### Negative

- **Not durable by default**: Redis pub/sub is fire-and-forget. For durable event delivery, Redis Streams (Stream type) must be used, which is different from pub/sub
- **No replay**: Unlike Kafka, Redis pub/sub does not support replaying events from an offset. For replay capability, a separate Kafka or NATS JetStream backend would be needed
- **Single-node Redis limitation**: Without Redis Cluster, the EventBus is limited to single-primary Redis. For HA, Redis Sentinel or Cluster is required (already planned for S20)

---

## Migration Path

FastStream's broker-agnostic API means swapping to NATS or Kafka is a one-line change:

```python
# Current (Redis)
from faststream.redis import RedisBroker
broker = RedisBroker(redis_url)

# Future (NATS — same interface)
from faststream.nats import NATSBroker
broker = NATSBroker(nats_url)
```

When scale demands Kafka durability and replay, swap `RedisBroker` → `KafkaBroker` in `EventBus._create_broker()` and update the broker URL in config.

---

## Verification

```bash
# Verify EventBus is using Redis broker
python -c "
from src.backend.infrastructure.clients.messaging.event_bus import EventBus
eb = EventBus()
assert 'Redis' in type(eb._broker).__name__, 'EventBus must use RedisBroker'
print('EventBus backend: RedisBroker — OK')
"

# Verify schema validation is enabled
python -c "
from src.backend.infrastructure.clients.messaging.event_bus import EventBus
eb = EventBus()
assert eb._schema_validation is not None, 'Schema validation must be enabled'
print('EventBus schema validation: enabled — OK')
"
```

---

## Relation to Other ADRs

- **ADR-0057** (Pure ASGI Middleware Chain): FastStream is part of the V15 R-V15-7 stack alongside APScheduler and Temporal
- **S19 K4 W3** (Banking AI Processors): Banking AI processors use `EventBus` for async KYC/AML events
- **S19 K4 W6** (Adaptive RAG Strategy): `RAGStrategySelector` can emit events via EventBus for retrieval strategy decisions
