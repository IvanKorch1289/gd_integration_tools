# S13 Circuit Breaker Phase 4 Staging Rollout — Operational Runbook

> **Purpose**: Step-by-step procedure for enabling `circuit_breaker_use_registry`
> feature flag in dev → staging → production environments. Operational
> counterpart to design document `docs/adr/0276-s13-phase4-staging-rollout-plan-cycle-284.md`.
>
> **Audience**: DevOps, security ops, backend team.
> **Status**: READY (pending Redis HA infrastructure approval + ops sign-off).

## Architecture Context

Per ADR-0251, ADR-0268, ADR-0276:

- **Phases 1-3.5** (S47-S52): all complete. BreakerRegistry, BreakerPolicyAdapter,
  legacy deque path removed, 488 middleware tests pass, 15 adapter tests pass.
- **Phase 4** (this sprint): enable `circuit_breaker_use_registry` flag in
  dev → staging → prod with monitoring between stages.
- **Mechanism**: `CircuitBreakerMiddleware` reads flag; when True, uses
  `BreakerPolicyAdapter` (state via `BreakerRegistry`, multi-pod safe via
  Redis UOW). When False, uses `SlidingWindowBreaker` (single-process).

**Source code**: `src/backend/entrypoints/middlewares/circuit_breaker.py:316-341`
(registry dispatch path).

---

## Pre-flight Checklist

### Code readiness

- [ ] All middleware tests pass (488 currently)
- [ ] Adapter tests pass with real BreakerRegistry (15 currently)
- [ ] Multi-pod integration tests pass (6 currently)
- [ ] `circuit_breaker_use_registry` flag exposed in `feature_flags` config

### Infrastructure

- [ ] Redis HA configured in target environment (Sentinel or Cluster)
- [ ] `REDIS_URL` configured for `BreakerRegistry` UOW
- [ ] Connection pooling tuned for expected QPS
- [ ] Redis health monitoring enabled (Prometheus + alerts)

### Configuration

- [ ] Default `circuit_breaker_use_registry=false` in feature flags
- [ ] `BreakerPolicy` defaults: `failure_threshold=5, window_seconds=60, reset_timeout=30`
- [ ] Per-route policies configured (e.g., `/api/v1/slow_external_route` lower threshold)

### Observability

- [ ] Metrics: circuit OPEN rate, registry sync lag, middleware errors, p99 latency
- [ ] Audit logs: `Circuit OPEN (registry adapter) — rejecting request for /path`
- [ ] Dashboards: Circuit Breaker Overview panel

### Pre-rollout validation (per ADR-0276 §4)

- [ ] All middleware tests pass
- [ ] Adapter tests pass with real purgatory
- [ ] Multi-pod tests pass
- [ ] Redis HA configured
- [ ] Feature flag exposed

### Automated pre-flight check (S64 W1)

**Use the pre-flight script before enabling the flag in any environment**:

```bash
# Phase 1 Dev rollout
./scripts/verify_s13_phase4_readiness.sh dev

# Phase 2 Staging rollout
REDIS_ENABLED=true ./scripts/verify_s13_phase4_readiness.sh staging

# Phase 3 Production rollout
REDIS_ENABLED=true ./scripts/verify_s13_phase4_readiness.sh prod
```

**What the script verifies**:
1. `circuit_breaker_use_registry` flag in `RedisSettings` ✓
2. Middleware reads the flag ✓
3. `BreakerPolicyAdapter` exists + wired ✓
4. Prometheus metrics for circuit breaker ✓
5. Sentinel support enabled (S59 W2) ✓
6. Circuit breaker test suite passes ✓
7. Environment-specific prerequisites (Redis HA for staging/prod)

**Exit codes**: 0 = ready for rollout, 1 = check failed, 2 = env error.
- [ ] Monitoring dashboards include CB metrics
- [ ] Runbook documented (this document)

---

## Phase 1: Dev Environment (Week 1)

### Step 1.1: Enable flag

```bash
# Set feature flag via environment variable
kubectl --context=dev set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true

# Wait for rollout
kubectl --context=dev rollout status deployment/api-gateway

# Verify flag enabled (should log "Circuit OPEN (registry adapter)")
kubectl --context=dev logs -l app=api-gateway | grep "registry adapter"
```

### Step 1.2: Smoke test

```bash
# Healthy endpoint → 200
curl https://dev-api.example.com/api/v1/health
# Expected: 200 OK

# Make multiple requests, observe circuit behavior
for i in {1..10}; do
  curl -s -o /dev/null -w "%{http_code}\n" https://dev-api.example.com/api/v1/slow_route
done
# Expected: mix of 200 (allowed) and possibly 503 (circuit open if failures)

# Trigger circuit open (simulate upstream failures)
# Note: requires injection mechanism (load test with errors)
```

### Step 1.3: Verify log format

Log lines to expect:
```
INFO: Circuit OPEN (registry adapter) — rejecting request for /api/v1/slow_route
INFO: breaker OPENED: route=/api/v1/slow_route after 5 failures exc=ConnectionError
INFO: breaker CLOSED via half-open probe: route=/api/v1/slow_route
```

### Step 1.4: Monitor dev for 3 days

Check Grafana dashboard:
- Circuit OPEN rate: should be < 5% of requests
- Middleware error rate: should be 0% (no exceptions in adapter)
- p99 latency: should be within +50ms of baseline

### Step 1.5: Go/no-go decision

- [ ] No critical issues detected in 3-day monitoring
- [ ] All metrics within thresholds
- [ ] No rollback events triggered

If all green → proceed to staging.

---

## Phase 2: Staging Environment (Week 2)

### Step 2.1: Pre-deploy verification

```bash
# Verify Redis is reachable from staging pods
kubectl --context=staging exec -it <pod> -- sh -c 'echo PING | nc redis 6379'

# Verify REDIS_URL is set
kubectl --context=staging get deployment api-gateway -o yaml | grep REDIS_URL
```

### Step 2.2: Deploy with flag OFF first (baseline)

```bash
# Ensure flag is OFF in staging (default state)
kubectl --context=staging set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=false

# Wait for rollout
kubectl --context=staging rollout status deployment/api-gateway

# Run smoke test
curl https://staging-api.example.com/api/v1/health
# Expected: 200 OK (baseline behavior, sliding window breaker)
```

### Step 2.3: Enable flag

```bash
# Enable registry-backed path
kubectl --context=staging set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true

# Wait for rollout
kubectl --context=staging rollout status deployment/api-gateway
```

### Step 2.4: Multi-pod test

```bash
# Scale to 2 instances
kubectl --context=staging scale deployment/api-gateway --replicas=2

# Trigger circuit open on pod A
# Verify pod B sees OPEN state (cross-pod propagation)
# This requires Redis state sync to work correctly

# Check both pods for OPEN state
kubectl --context=staging logs -l app=api-gateway | grep "OPEN" | head -10
```

### Step 2.5: Monitor staging for 5 days

| Metric | Threshold | Action |
|---|---|---|
| Circuit OPEN rate | > 5% | Investigate upstream |
| Registry sync lag (Redis) | > 100ms | Check Redis health |
| Middleware error rate | > 0.1% | Roll back |
| p99 latency | > +50ms vs baseline | Investigate overhead |

### Step 2.6: Go/no-go decision

- [ ] 5-day monitoring clean
- [ ] Multi-pod sync verified
- [ ] No critical incidents
- [ ] Metrics within thresholds

If all green → proceed to production canary.

---

## Phase 3: Production Rollout (Week 3-4)

### Step 3.1: Canary 10%

```bash
# Enable flag on 10% of pods (1 of 10)
kubectl --context=prod label pods -l app=api-gateway \
  circuit-breaker-registry-canary=true --selector='app=api-gateway' --dry-run=server

# Or use a canary deployment strategy with the flag enabled only on canary pods
kubectl --context=prod set env deployment/api-gateway-canary \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true

# Wait for rollout
kubectl --context=prod rollout status deployment/api-gateway-canary
```

### Step 3.2: Monitor canary for 3 days

Same metrics as staging (5-day equivalent for prod).

### Step 3.3: Ramp to 50%

```bash
# Increase canary percentage
# (depends on deployment strategy — e.g., Argo Rollouts, Flagger)
kubectl --context=prod set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true --selector='...50% of pods...'
```

### Step 3.4: Monitor 50% for 3 days

Same metrics + comparison to baseline.

### Step 3.5: Full rollout (100%)

```bash
# Enable flag on all production pods
kubectl --context=prod set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true

# Wait for rollout
kubectl --context=prod rollout status deployment/api-gateway
```

### Step 3.6: Monitor 100% for 7 days

This is the critical soak period before flag removal.

### Step 3.7: Flag removal (after 7-day stable 100%)

After confirming stability:
- Remove `circuit_breaker_use_registry` flag check
- Default to registry-backed path
- Code becomes the canonical implementation

---

## Rollback Procedure

### Immediate rollback (within minutes)

```bash
# Disable flag (instant rollback to sliding window breaker)
kubectl --context=<env> set env deployment/api-gateway \
  FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=false

# Wait for rollout
# Middleware falls back to SlidingWindowBreaker (existing behavior)
```

### Full rollback (if flag insufficient)

```bash
# Revert code deployment
kubectl --context=<env> rollout undo deployment/api-gateway

# Verify
curl https://<env>-api.example.com/api/v1/health
```

### Post-rollback

1. Document root cause in incident report
2. Update `ADR-0276` with findings
3. Re-plan Phase 4 with mitigations

---

## Monitoring & Alerting

### Critical alerts (page on-call)

| Alert | Condition | Severity |
|---|---|---|
| Redis down | `redis_connected = 0` for > 1 min | P1 |
| Circuit OPEN rate spike | > 5% of requests | P2 |
| Registry sync lag | > 100ms for > 5 min | P2 |
| Middleware error rate | > 0.1% | P1 |
| p99 latency regression | > +50ms for > 10 min | P2 |

### Grafana dashboard panels

**Circuit Breaker Overview**:

- Circuit OPEN rate (5m, 1h, 24h windows)
- Registry sync lag (Redis read/write latency)
- Middleware error rate
- p99 latency comparison (registry vs sliding window)
- Per-route circuit state distribution

### Prometheus metrics

- `circuit_breaker_open_total{route=...}` — counter
- `circuit_breaker_state{route=...,state=...}` — gauge
- `circuit_breaker_registry_sync_duration_seconds` — histogram

---

## Test Infrastructure

Existing tests (S50 W1, S51 W2, S52 W1):
- `tests/unit/entrypoints/middlewares/test_circuit_breaker_registry_path.py` — 191 lines
- `tests/integration/core/resilience/` — integration tests
- Total: 488 middleware + 15 adapter tests

To run before each rollout stage:
```bash
uv run pytest tests/unit/entrypoints/middlewares/ -v
uv run pytest tests/integration/core/resilience/ -v
```

---

## References

- ADR-0276 — Phase 4 staging rollout plan (design)
- ADR-0268 — 4-phase rollout plan (parent)
- ADR-0270 — Phase 2b middleware wiring
- ADR-0273 — Phase 2b-2 __call__ dispatch fix
- ADR-0274 — Phase 2c legacy removal
- ADR-0275 — Purgatory integration
- `src/backend/entrypoints/middlewares/circuit_breaker.py` — middleware impl
- `src/backend/core/resilience/breaker_policy_adapter.py` — adapter impl
- `src/backend/core/resilience/breaker.py` — BreakerRegistry
- `docs/security/MOBILE_JWT_PRODUCTION_FLIP_RUNBOOK.md` — sibling runbook (template)

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-08-25 | Initial runbook created (S58 W1) | Kimi Code |
| 2026-08-25 | Pre-flight script added (S64 W1) | Kimi Code |
| 2026-08-25 | Phase 4 readiness: 6/6 checks pass | Kimi Code (S64) |
| 2026-08-25 | Post-rollout monitoring script (S66 W1) | Kimi Code |
| 2026-08-25 | 1 audit candidate fixed (skill_registry.py) | Kimi Code (S66 W2) |
| TBD | Dev rollout date | TBD |
| TBD | Staging rollout date | TBD |
| TBD | Production rollout date | TBD |
