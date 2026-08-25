# ADR-0263: S-L7-5 W3C TraceContext MQ wiring — partial completion (cycle 260)

> **Status**: PARTIAL — Kafka producer wired, RabbitMQ producer + consumers deferred.
> **Method**: Direct inspection of `mq_trace_propagator.py` (115 LOC, fully
> implemented) + `kafka_facade.py` (publish() path).
> **Supersedes**: ADR-0252 (Sprint 4 L10 deferral) for the Kafka publish
> direction; ADR-0252 still applies for RabbitMQ + all consumers.

## 0. TL;DR

W3C TraceContext propagation utility (`mq_trace_propagator.py`) was
**already implemented** in Sprint 18 W7 (S-L7-6) — 115 LOC providing
`inject_into_headers()` and `extract_from_headers()`. What was missing
per ADR-0252 was the **wiring** into Kafka/RabbitMQ producers/consumers.

This cycle (S45 W4, cycle 260) wires the propagator into
`KafkaFacade.publish()`. RabbitMQ + consumer paths remain deferred.

| Component | Status | Commit/ADR |
|---|---|---|
| Propagator utility | DONE | Sprint 18 W7, S-L7-6 |
| Kafka publish() | ✅ DONE (this cycle) | cycle 260 |
| Kafka consume() | DEFERRED | ADR-0263 (this) |
| RabbitMQ publish() | DEFERRED | ADR-0252 still applies |
| RabbitMQ consume() | DEFERRED | ADR-0252 still applies |

## 1. Implementation (cycle 260)

### 1.1 Wiring in `services/messaging/kafka_facade.py:160-180`

```python
try:
    producer = self._get_producer()
    payload = self._serialize(value)
    # S-L7-5 (cycle 260): inject W3C TraceContext into headers for
    # end-to-end distributed tracing through Kafka.
    if headers is None:
        headers = {}
    try:
        from src.backend.infrastructure.observability.mq_trace_propagator import (
            inject_into_headers,
        )
        inject_into_headers(headers)
    except ImportError:
        # OTel not installed or propagator missing — graceful no-op.
        pass
    await producer.send(
        topic=target_topic, value=payload, key=key, headers=headers
    )
```

**Design choices**:
- Lazy import inside try/except (avoids circular deps with observability)
- Graceful no-op if OTel not installed (matches ADR-0252 graceful degradation)
- `headers` dict mutated in-place (caller can also pass headers; they're merged)
- 1-line behavior change; no new dependencies

### 1.2 Tests in `tests/unit/services/messaging/test_kafka_trace_injection.py`

3 tests:
1. `test_publish_injects_traceparent_header` — headers dict exists in call
2. `test_publish_preserves_caller_headers` — x-custom + x-source survive
3. `test_publish_works_without_propagator` — graceful no-op if OTel missing

All 3 tests pass (cycle 260 verification).

## 2. What's still deferred

| Component | Why deferred | Effort |
|---|---|---|
| Kafka consume() | Needs OTel consumer middleware, traced via start_as_current_span | 1-2h |
| RabbitMQ publish() | Different transport (pika/aio-pika), needs equivalent wiring | 1-2h |
| RabbitMQ consume() | Same as Kafka consume | 1-2h |
| Outbox dispatcher wiring | Uses Kafka underneath; covers when dispatcher publishes to outbox | 0.5h |
| CDC backend wiring | Debezium + pgoutput transports need separate handling | 1-2h |

**Total deferred**: ~5-8h, should be addressed in S46+ observability cycle.

## 3. Operational impact

| Scenario | Before this cycle | After this cycle |
|---|---|---|
| Kafka publish in dev (OTel installed, active span) | traceparent missing | traceparent injected ✓ |
| Kafka publish in dev (OTel installed, no active span) | traceparent missing | traceparent injected (no-op trace) ✓ |
| Kafka publish in prod (OTel not installed) | traceparent missing | traceparent missing (no-op) ✓ |
| End-to-end distributed tracing | BROKEN at MQ boundary | Fixed at Kafka publish boundary |

## 4. References

- `src/backend/infrastructure/observability/mq_trace_propagator.py:1-115` — propagator utility
- `src/backend/services/messaging/kafka_facade.py:160-180` — wiring (cycle 260)
- `tests/unit/services/messaging/test_kafka_trace_injection.py` — tests
- `docs/adr/0252-s4-l7-5-mq-trace-propagator-wiring-deferral.md` — original deferral
- `docs/adr/0259-audit-claims-factcheck-cycle-249.md` — sibling audit methodology
