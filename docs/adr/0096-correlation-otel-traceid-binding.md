# ADR-0096: Correlation→OTel trace_id binding (formalize S18 W7 + S-L7-2/6)

**Date:** 2026-06-08
**Status:** Accepted (S70 W2 — formalize decision, S67 W2 backlog)
**Sprint:** S70
**Deciders:** core/observability team
**Supersedes:** — (formalizes S18 W7 + S-L7-2 + S-L7-6)
**Related:** ADR-0051, correlation.py, mq_trace_propagator.py

## Context

Backlog S67-W2: "Correlation→OTel trace_id binding" (от роевого анализа V22).
Подразумевалось что correlation_id не связан с OTel trace_id.

Audit проведён 2026-06-08 — **Correlation→OTel binding ALREADY PRODUCTION-READY**
(746 LOC, 6 модулей).

**Components (verified wc -l):**
```
src/backend/infrastructure/observability/correlation.py           68 LOC
src/backend/infrastructure/observability/otel_auto.py            266 LOC
src/backend/infrastructure/observability/mq_trace_propagator.py  113 LOC
src/backend/entrypoints/middlewares/otel_middleware.py           227 LOC
src/backend/entrypoints/grpc/correlation.py                       58 LOC
src/backend/entrypoints/middlewares/correlation.py                14 LOC (re-export)
Total:                                                           746 LOC
```

**Plus:**
* `src/backend/infrastructure/observability/otel/` (subdir)
* `src/backend/core/request_context.py` (correlation_id context var)
* `src/backend/core/di/contexts.py` (DI integration)
* W3C TraceContext standard: `traceparent` / `tracestate` headers

## Decision

Признать Correlation→OTel binding PRODUCTION-READY. Реализация S18 W7 +
S-L7-2 (OTel contextvar) + S-L7-6 (MQ propagation) closed.

**Architecture:**
1. **HTTP ingress** (`entrypoints/middlewares/correlation.py` + `otel_middleware.py`):
   * Extract W3C `traceparent` из request header (или generate new)
   * Set OTel contextvar (`trace_id` / `span_id`)
   * Inject OTel context в `request.correlation_id` (для backward compat)
2. **gRPC** (`entrypoints/grpc/correlation.py`):
   * gRPC metadata propagation
3. **MQ publish** (`mq_trace_propagator.py:inject_into_headers`):
   * W3C `traceparent` в Kafka/RabbitMQ/NATS headers
4. **MQ consume** (`mq_trace_propagator.py:extract_from_headers`):
   * Extract context из headers → start downstream span
5. **Logging** (`otel_auto.py`):
   * structlog auto-injection `trace_id` / `span_id` в каждый log record
6. **Audit** (services/audit/):
   * `correlation_id` propagated в audit events

**Features (verified):**
* **W3C TraceContext standard** — `traceparent` / `tracestate` headers
* **Multi-protocol** — HTTP + gRPC + Kafka + RabbitMQ + NATS
* **OTel propagator OOB** — default global propagator (no manual config)
* **Graceful degradation** — no-op if OTel not installed
* **bytes↔str transparent** — Kafka headers (bytes) vs Rabbit (str)
* **structlog auto-injection** — `trace_id` в каждый log record

**Usage:**
```python
# HTTP request: client provides traceparent
curl -H "traceparent: 00-<32hex>-<16hex>-01" /api/v1/users

# Server: extract, set context, propagate to MQ
# In downstream MQ publish:
from src.backend.infrastructure.observability.mq_trace_propagator import (
    inject_into_headers,
)
headers: dict[str, str] = {}
inject_into_headers(headers)  # adds traceparent
await producer.send("topic", value=payload, headers=headers)
```

## Consequences

### Positive

* End-to-end distributed tracing через все протоколы (HTTP+gRPC+MQ+DB)
* W3C standard compliance — interop с другими OTel-инструментированными
  сервисами (Jaeger, Tempo, Datadog)
* Graceful degradation — OTel optional (no hard dep)
* structlog auto-injection — каждый log имеет trace_id без boilerplate
* Audit events correlated — `correlation_id` в workflow_audit_sink

### Negative

* 6 модулей distributed — нужен mental model
* MQ headers: каждый брокер использует свой формат
  (Kafka=bytes, Rabbit=str, NATS=metadata) — нужна transparent conversion
* OTel contextvar overhead (минимальный, но присутствует)

### Neutral

* 746 LOC distributed across 6 модулей
* core/request_context.py = correlation_id contextvar
* core/di/contexts.py = DI integration

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `correlation.py` (correlation_id) | DONE | infrastructure/observability/correlation.py |
| `otel_auto.py` (structlog auto) | DONE | infrastructure/observability/otel_auto.py |
| `otel_middleware.py` (HTTP) | DONE | entrypoints/middlewares/otel_middleware.py |
| `correlation.py` middleware (HTTP) | DONE | entrypoints/middlewares/correlation.py |
| `correlation.py` (gRPC) | DONE | entrypoints/grpc/correlation.py |
| `mq_trace_propagator.py` (inject/extract) | DONE | infrastructure/observability/mq_trace_propagator.py |
| W3C TraceContext standard | DONE | mq_trace_propagator.py |
| `core/request_context.py` (contextvar) | DONE | core/request_context.py |
| `core/di/contexts.py` (DI) | DONE | core/di/contexts.py |
| `infrastructure/observability/otel/` (subdir) | DONE | infrastructure/observability/otel/ |
| structlog auto-injection trace_id | DONE | otel_auto.py |
| Audit correlation | DONE | services/audit/workflow_audit_sink.py |
| Correlation→OTel graph viz в Streamlit | TODO | out of scope |
| Per-tenant trace sampling override | TODO | out of scope |

## References

* `src/backend/infrastructure/observability/correlation.py` (68 LOC)
* `src/backend/infrastructure/observability/otel_auto.py` (266 LOC)
* `src/backend/infrastructure/observability/mq_trace_propagator.py` (113 LOC)
* `src/backend/entrypoints/middlewares/otel_middleware.py` (227 LOC)
* `src/backend/entrypoints/middlewares/correlation.py` (14 LOC)
* `src/backend/entrypoints/grpc/correlation.py` (58 LOC)
* `src/backend/infrastructure/observability/otel/` (subdir)
* `src/backend/core/request_context.py`
* `src/backend/core/di/contexts.py`
* S18 W7: original mq_trace_propagator sprint
* S-L7-2: OTel contextvar binding (resolved in S18)
* S-L7-6: connect pool metrics (related, separate backlog)
* W3C TraceContext: https://www.w3.org/TR/trace-context/
* ADR-0051 (parent: in-house observability primitives)
