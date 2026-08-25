# ADR-0276: S13 Phase 4 Staging Rollout Plan (cycle 284)

> **Status**: PROPOSED for S52+ execution.
> **Method**: Synthesis from S48-S51 work + ADR-0268 ceremony plan.
> **Prerequisite**: All previous phases complete (1, 2a, 2b, 2b-2, 2c, 3, 3.5).

## 0. Phase 4 scope

Enable `circuit_breaker_use_registry` feature flag in DEV environment
first, then STAGING, then PROD. Rollout is per-environment with monitoring
between stages.

## 1. Rollout phases

### 1.1 Dev environment (Week 1)

1. Set `FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true` in dev env config
2. Verify middleware uses registry path (logs `Circuit OPEN (registry adapter)`)
3. Run integration tests against real deps
4. Monitor for 3 days
5. If OK → proceed to staging

### 1.2 Staging environment (Week 2)

1. Set flag in staging env
2. Set up Redis (shared with prod prep)
3. Configure `REDIS_URL` for BreakerRegistry UOW
4. Multi-pod test: deploy 2 instances, verify cross-pod state propagation
5. Monitor for 5 days (more conservative for staging)
6. If OK → proceed to prod

### 1.3 Production environment (Week 3-4)

1. Canary release: 10% of pods with flag ON for 3 days
2. Monitor error rates, p99 latency, breaker open events
3. Ramp to 50% for 3 days
4. Full rollout (100%) for 7 days
5. After 7 days stable: remove flag check, default to registry

## 2. Monitoring requirements

| Metric | Threshold | Action |
|---|---|---|
| Circuit OPEN rate | > 5% requests | Investigate upstream service health |
| Registry sync lag (Redis) | > 100ms | Check Redis health, network |
| Middleware error rate | > 0.1% | Roll back, investigate |
| p99 latency | > +50ms vs baseline | Check registry overhead |

## 3. Rollback plan

If production issues detected:
1. Set `FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=false` (instant rollback)
2. Middleware falls back to SlidingWindowBreaker path (existing behavior)
3. Investigate logs + middleware errors
4. Re-enable after fix

## 4. Pre-rollout checklist

- [ ] All middleware tests pass (488 currently)
- [ ] Adapter tests pass with real purgatory (15 currently)
- [ ] Multi-pod tests pass (6 currently)
- [ ] Redis HA configured in target env
- [ ] Feature flag exposed in feature_flags config
- [ ] Monitoring dashboards include CB metrics
- [ ] Runbook documented for ops team

## 5. ADR chain (Phase 4 references)

- ADR-0251 — original DECLINED + ceremony plan
- ADR-0266 — S13 reaffirmation in S47
- ADR-0268 — 4-phase rollout plan
- ADR-0269 — Phase 2a foundation (BreakerPolicyAdapter)
- ADR-0270 — Sprint 50 plan
- ADR-0273 — Phase 2b-2 __call__ fix
- ADR-0274 — Phase 2c legacy removal
- ADR-0275 — Purgatory ContextManager integration
- ADR-0276 — **this document** — Phase 4 staging rollout plan

## 6. Open questions

1. Redis cluster HA strategy (single instance vs cluster)?
2. Breaker state TTL in Redis (how long to keep old states)?
3. Monitoring tooling: Prometheus exporter for `gd_integration_test_coverage_percent` etc. — already noted as Sprint 45 W4 follow-up, still pending
4. Operational runbook owner (SRE team or backend team)?

## 7. References

- `src/backend/entrypoints/middlewares/circuit_breaker.py` — middleware (cycle 282)
- `src/backend/core/resilience/breaker_policy_adapter.py` — adapter (cycle 283)
- `src/backend/core/resilience/breaker.py` — BreakerRegistry (cycle 270)
- ADR-0268 — original 4-phase plan
