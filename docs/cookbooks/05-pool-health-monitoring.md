# Cookbook 05: Pool Health Monitoring for LiteLLM Gateway

**Sprint**: S80
**ADR**: [ADR-0162](../adr/0162-sprint-80-litemlm-pool-closure.md)
**Status**: Production-ready

## Use Case

LiteLLM gateway обслуживает 50+ AI tenants. Каждый tenant использует разные
models (GPT-4, Claude, Gemini). Если один model pool исчерпал connections —
**нужно сразу видеть**, какой pool и какой tenant, а не ловить `ConnectionPoolError`
в production.

## Solution

`PoolHealthMonitor` (S80 W1) + LiteLLM auto-registration (S80 W2) +
`/health/pools` endpoint (S80 W3).

## Recipe

### Step 1: Enable feature flag

```yaml
# config/features.yaml
flags:
  LITELLM_POOL_MONITOR: true  # default ON in prod
```

### Step 2: Configure pool policies

```yaml
# config/pools.yaml
pools:
  litellm_gpt4:
    max_size: 50
    acquire_timeout_seconds: 10
    health_check_interval_seconds: 30
  litellm_claude:
    max_size: 30
    acquire_timeout_seconds: 5
    health_check_interval_seconds: 30
  redis_default:
    max_size: 20
    acquire_timeout_seconds: 1
    health_check_interval_seconds: 60
```

### Step 3: Use in code

```python
from gd_integration_tools.infrastructure.resilience.pool_registration import (
    PoolHealthMonitor, PoolStatus
)

monitor = PoolHealthMonitor.from_yaml("config/pools.yaml")

# Acquire with timeout
async with monitor.acquire("litellm_gpt4", timeout=10) as conn:
    response = await conn.completion(model="gpt-4", messages=[...])

# Check pool status
status = monitor.status("litellm_gpt4")
# -> PoolStatus(available=42, in_use=8, waiters=0, total=50, healthy=True)
```

### Step 4: Expose health endpoint

```python
from fastapi import FastAPI
from gd_integration_tools.entrypoints.health.pools import router as pools_router

app = FastAPI()
app.include_router(pools_router)

# GET /health/pools
# -> {"pools": {
#   "litellm_gpt4": {"available": 42, "in_use": 8, "healthy": true, "wait_time_p99_ms": 12},
#   "litellm_claude": {"available": 28, "in_use": 2, "healthy": true, "wait_time_p99_ms": 8},
#   "redis_default": {"available": 18, "in_use": 2, "healthy": true, "wait_time_p99_ms": 1}
# }}
```

### Step 5: Alerting

```yaml
# config/alerts.yaml
alerts:
  - name: pool_saturation
    condition: pool.in_use / pool.total > 0.9
    duration: 5m
    severity: warning
    notification: slack:#ops
  - name: pool_unhealthy
    condition: pool.healthy == false
    duration: 1m
    severity: critical
    notification: pagerduty:oncall
```

## Key Points

- **Per-pool metrics** — не aggregate, чтобы видеть **какой именно** pool/model/tenant проблемный
- **acquire_timeout** — hard ceiling, не ждать бесконечно (cascade prevention)
- **health_check_interval** — background task каждые 30s, не дёргает каждый acquire
- **Multi-instance safe** — state в `PoolHealthMonitor` instance per process, Redis-backed для cross-instance aggregation (S80 W2 future work)

## Related

- `02-outbox-multi-instance-claim.md` — multi-instance patterns
- `04-circuit-breaker-middleware.md` — combine для layered resilience
