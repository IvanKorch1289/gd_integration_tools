# Cookbook 04: Circuit Breaker для External Service Calls

**Sprint**: S81
**ADR**: [ADR-0163](../adr/0163-sprint-81-circuit-breaker-middleware-closure.md)
**Status**: Production-ready

## Use Case

Integration вызывает внешний SOAP-сервис (billing system). В пятницу вечером
billing ложится — без circuit breaker все worker'ы тратят 30s на timeout × retry,
event loop забивается, и **healthy services тоже деградируют** (cascade failure).

## Solution

`CircuitBreakerMiddleware` (S81 W1) + `CircuitBreakerRegistry` (per-service config)
+ FastAPI middleware integration (S81 W2).

## Recipe

### Step 1: Define circuit breaker policy

```yaml
# config/resilience.yaml
circuit_breakers:
  billing_service:
    failure_threshold: 5        # open after 5 consecutive failures
    recovery_timeout_seconds: 60  # try half-open after 60s
    half_open_max_calls: 3      # allow 3 test calls in half-open
    excluded_exceptions:        # don't count as failures
      - ValidationError
      - AuthenticationError
  external_ai:
    failure_threshold: 3
    recovery_timeout_seconds: 30
    half_open_max_calls: 1
```

### Step 2: Use in endpoint

```python
from fastapi import FastAPI, Request
from gd_integration_tools.entrypoints.middleware.circuit_breaker import (
    CircuitBreakerMiddleware
)
from gd_integration_tools.infrastructure.resilience.registry import (
    CircuitBreakerRegistry
)

app = FastAPI()
registry = CircuitBreakerRegistry.from_yaml("config/resilience.yaml")
app.add_middleware(CircuitBreakerMiddleware, registry=registry)

@app.post("/billing/invoice")
async def create_invoice(request: Request):
    # Middleware auto-tracks success/failure of this handler
    cb = request.state.circuit_breakers["billing_service"]
    if cb.state == "open":
        raise HTTPException(503, "billing_service is unavailable, retry later")
    try:
        result = await billing_client.create_invoice(await request.json())
        cb.record_success()
        return result
    except Exception as e:
        if not isinstance(e, tuple(registry.excluded_exceptions["billing_service"])):
            cb.record_failure()
        raise
```

### Step 3: Observe circuit state

```python
from gd_integration_tools.infrastructure.observability.metrics import (
    circuit_breaker_state_gauge
)

# Prometheus metric: circuit_breaker_state{service="billing_service"} 0=closed, 1=half-open, 2=open
for service, state in registry.states().items():
    circuit_breaker_state_gauge.labels(service=service).set(state.value)
```

## Key Points

- **No global state** — `CircuitBreakerRegistry` is request-scoped, multi-instance safe
- **Per-service policy** — different breakers для different failure profiles
- **Excluded exceptions** — `ValidationError` не открывает breaker (client bug ≠ service down)
- **State machine**: CLOSED → OPEN (failures) → HALF_OPEN (after recovery_timeout) → CLOSED (test calls succeed)

## Anti-patterns

- **Don't** use singleton circuit breaker (race condition in multi-process)
- **Don't** count client validation errors as failures
- **Don't** set `recovery_timeout` < 10s (thundering herd на half-open)
- **Don't** use one global breaker for all services (cross-domain contamination)

## Related

- `01-ai-agent-tools-whitelist.md` — agent tool filter
- `02-outbox-multi-instance-claim.md` — multi-instance safety
- `03-e2b-jupyter-sandbox.md` — sandboxed AI code execution
