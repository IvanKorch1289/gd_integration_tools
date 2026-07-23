# Cycle 2 — Analyst 4 (Infrastructure) — Consolidated

**Status**: success

## P0 — Critical
1. **`src/backend/infrastructure/database/database/initializer.py:222` — BROKEN MODULE**: `@resilient(name="postgres_query", max_attempts=3)` uses symbol but **never imports it**. Sibling files (clickhouse.py, nats_pool.py, vector_store.py) correctly import. Confirmed: `NameError: name 'resilient' is not defined`. Database core bootstrap broken on import.
2. **DLQ persistence deferred** — `src/backend/infrastructure/notifications/gateway.py:317` — comment promises follow-up that never landed. Messages lost on retry exhaustion.

## P0 — Layer/credential
- 0 infra→entrypoints or infra→services imports (verified by grep)
- 0 bare `except:` (48 `except Exception:` are all defensive/noqa-marked)
- `src/backend/infrastructure/sources/mq.py:119` — `RabbitBroker(self._url or "amqp://guest:guest@localhost/")` default credential in source

## P0 — Connection pool
- No `pool.acquire()` leaks found (all in asynccontextmanager)
- `SmartSessionManager.acquire` properly closes session in finally
- **`channel_ready()` without timeout hazard**: `grpc_pool.py:80,132,147` and `grpc_sink.py:118` — can hang pool indefinitely

## P0 — Saga idempotency
- `workflow/saga_state.py:117-176` enforces `(workflow_id, run_id)` uniqueness
- DLQ writers (kafka, rabbit, dlq_base) have idempotent producer keys via `dlq_id`
- **Outbox dispatcher no consumer-side idempotency token** — `messaging/outbox/dispatcher.py:266-327` relies on caller-supplied `ack` callback

## P1 — Hardcoded timeouts
- 30+ files with hardcoded `timeout` values (1.0s, 2.0s, 5.0s, 10.0s, 30.0s, 60.0s, 3600.0s)
- Sinks: http/mqtt/grpc/nats_jetstream/sms/webhook all default to 10.0s

## P1 — CDC backpressure
- `CdcPostgresLogicalSource` — backpressure absent (sources/cdc_postgres_logical.py:201-211)
- `CDCSource._run` — no backpressure on `_emit` (sources/cdc.py:127-133)
- `CDC listen_notify_backend` has bounded queue (maxsize=1000) but **silent drop** on overflow (strategies.py:229-231)

## P1 — Misc
- `initializer.py:222` — `@resilient` not imported (same as P0-1)
- `mq.py:119` — `guest:guest` default credential
- `nats_jetstream.py:90-99` — connection double-close (drain+close)
- `clients/external/logger.py:90` — Graylog UDP check_connection false positive
- `observability/otel_auto.py:251-265` — `AsyncPGInstrumentor` double-instrumentation hazard
- `s3.py:216` — bizarre `ServiceError(...).__class__(...)` pattern
- `webhook_sink.py:124` — `if "RPACallExhausted" in dir() else False` tautological
- `sql via .format()`: `sources/cdc_postgres_logical.py:162-170` (semi-controlled but risky)

## Verified clean
- 0 insecure random (all `random.X` are non-crypto with `# noqa: S311`)
- 0 infra→entrypoints/services
- 0 bare except
