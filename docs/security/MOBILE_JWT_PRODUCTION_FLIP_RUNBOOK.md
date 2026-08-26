# Mobile JWT Production Flip — Operational Runbook

> **Purpose**: Step-by-step procedure for enabling `mobile_jwt_enabled` feature
> flag in production. Combines security review evidence, operational
> checklists, and rollback procedures.
>
> **Audience**: DevOps, security ops, mobile team.
> **Status**: READY (pending OWASP team sign-off per `OWASP_V35_MOBILE_AUTH_EVIDENCE.md`).

## Pre-flight Checklist

### Security review

- [ ] OWASP team reviewed and signed off on
      `OWASP_V35_MOBILE_AUTH_EVIDENCE.md`
- [ ] Mobile team reviewed UX impact of family revocation (forced re-login on
      reuse detection)
- [ ] Security ops reviewed audit log retention policy

### Infrastructure

- [ ] Redis HA configuration approved (Sentinel or Cluster)
- [ ] Redis connection string configured: `REDIS_URL=redis://...`
- [ ] Redis health monitoring enabled (Prometheus + alert on Redis down)
- [ ] Connection pooling tuned for expected QPS

### Secrets

- [ ] `JWT_PUBLIC_KEY` (RS256/ES256) or `JWT_SECRET` (HS256) stored in Vault
- [ ] JWT keys rotated per policy (recommended: 90 days)
- [ ] No plaintext secrets in environment files or git

### Configuration

- [ ] `JWT_ALGORITHM` set (default: RS256)
- [ ] `JWT_ISSUER_WHITELIST` configured (e.g., `["gd-mobile-prod"]`)
- [ ] `JWT_AUDIENCE` set (e.g., `"gd-mobile-api"`)
- [ ] `MOBILE_RATE_LIMIT_MAX_REQUESTS` reviewed (default: 60/min)
- [ ] `MOBILE_RATE_LIMIT_WINDOW_SECONDS` reviewed (default: 60s)

### Observability

- [ ] Audit logs shipping to centralized log aggregation
- [ ] Dashboards configured: refresh rate, reuse events, family revocations
- [ ] Alerts configured: Redis down, JWT signature errors > threshold

---

## Deployment Procedure

### Phase 1: Staging deployment

```bash
# 1. Deploy code (unchanged from current)
kubectl apply -f deploy/k8s/mobile-auth-deployment.yaml

# 2. Wait for rollout
kubectl rollout status deployment/mobile-auth --timeout=5m

# 3. Verify health
curl https://staging.example.com/mobile/v1/health
```

### Phase 2: Enable Redis-backed rotation store

```bash
# Set environment variable in staging deployment
kubectl set env deployment/mobile-auth REDIS_ENABLED=true
kubectl rollout status deployment/mobile-auth

# Verify Redis connection in app logs
kubectl logs -l app=mobile-auth | grep "redis refresh store"
# Expected: no warnings about Redis unavailability
```

### Phase 3: Smoke test refresh rotation

```bash
# Issue test JWT (from staging auth provider)
TEST_JWT="eyJhbGciOi..."

# First refresh — should succeed (first-use)
curl -X POST https://staging.example.com/mobile/v1/auth/refresh \
  -H "Authorization: Bearer $TEST_JWT" \
  -d "device_id=11111111-2222-4333-8444-555555555555"
# Expected: 200 + new tokens

# Second refresh with SAME JWT — should fail (reuse)
curl -X POST https://staging.example.com/mobile/v1/auth/refresh \
  -H "Authorization: Bearer $TEST_JWT" \
  -d "device_id=11111111-2222-4333-8444-555555555555"
# Expected: 401 + "Family revoked" detail
```

### Phase 4: Enable mobile_jwt_enabled flag

```bash
# Enable in staging via feature flag admin API
curl -X PUT https://staging-admin.example.com/api/v1/admin/feature-flags/mobile_jwt_enabled \
  -H "Content-Type: application/json" \
  -d '{"value": true, "actor": "ops@example.com"}'

# Verify flag enabled
curl https://staging-admin.example.com/api/v1/admin/feature-flags | jq '.mobile_jwt_enabled'
```

### Phase 5: Monitor staging for 24 hours

Check the following metrics in Grafana:

| Metric | Expected | Action if abnormal |
|---|---|---|
| Refresh success rate | > 99% | Investigate JWT validation failures |
| Reuse detection events | < 1/day | Investigate if spike (attack?) |
| Family revocation events | < 1/week | Investigate (legitimate attack attempts) |
| JWT signature errors | < 0.1% | Check key rotation, clock skew |
| Refresh latency p99 | < 200ms | Check Redis health |

### Phase 6: Production deployment

**Only after 24h staging soak with no critical issues**.

```bash
# Deploy to production
kubectl apply -f deploy/k8s/mobile-auth-deployment.yaml --context=prod

# Same env vars as staging
kubectl --context=prod set env deployment/mobile-auth REDIS_ENABLED=true
# ... etc

# Wait for rollout, verify health
kubectl --context=prod rollout status deployment/mobile-auth
curl https://api.example.com/mobile/v1/health

# Enable feature flag in production (SAME admin API)
curl -X PUT https://admin.example.com/api/v1/admin/feature-flags/mobile_jwt_enabled \
  -H "Content-Type: application/json" \
  -d '{"value": true, "actor": "ops@example.com"}'
```

---

## Rollback Procedure

If critical issues arise after enabling `mobile_jwt_enabled`:

### Immediate rollback (within minutes)

```bash
# Disable the feature flag (revert to demo mode)
curl -X PUT https://admin.example.com/api/v1/admin/feature-flags/mobile_jwt_enabled \
  -H "Content-Type: application/json" \
  -d '{"value": false, "actor": "ops@example.com"}'

# Verify mobile clients are using demo auth (no JWT)
# This is a graceful transition — clients with valid demo refresh tokens continue working
```

### Full rollback (if feature flag insufficient)

```bash
# Revert code deployment
kubectl --context=prod rollout undo deployment/mobile-auth

# Restore previous version
kubectl --context=prod rollout status deployment/mobile-auth

# Verify
curl https://api.example.com/mobile/v1/health
```

### Post-rollback

1. Document root cause in incident report
2. Update `OWASP_V35_MOBILE_AUTH_EVIDENCE.md` with findings
3. Re-plan production flip with mitigations

---

## Monitoring & Alerting

### Critical alerts (page on-call)

| Alert | Condition | Severity |
|---|---|---|
| Redis down | `redis_connected = 0` for > 1 min | P1 |
| JWT validation failure rate | > 5% of refresh attempts | P2 |
| Family revocation spike | > 10 events/min (potential attack) | P1 |
| Refresh latency p99 | > 500ms for > 5 min | P2 |

### Dashboards

**Grafana dashboard: Mobile Auth Overview**

Panels:
- Refresh success rate (5m, 1h, 24h windows)
- Reuse detection events (count + rate)
- Family revocation events (count + rate)
- JWT signature errors by error type
- Refresh latency (p50, p95, p99)
- Redis health (connections, memory, ops/sec)

---

## Audit & Compliance

### Daily checks (ops)

- [ ] Review family revocation events (legitimate attack attempts)
- [ ] Verify Redis HA failover works (synthetic check)
- [ ] Check JWT key rotation status

### Weekly checks (security)

- [ ] Review audit logs for anomalies
- [ ] Verify all mobile clients are using JWT (no fallback to demo mode)
- [ ] Update OWASP team on production metrics

### Monthly checks (compliance)

- [ ] OWASP team review of audit logs
- [ ] Penetration testing for new attack vectors
- [ ] Update OWASP evidence document with current state

---

## References

- `OWASP_V35_MOBILE_AUTH_EVIDENCE.md` — control-by-control evidence
- `docs/security/AUTH.md` — general auth strategy
- `docs/adr/0265-owasp-jwt-checklist-review-cycle-263.md` — Phase 2 protections
- `docs/retros/SPRINT_56_*` — most recent sprint retro
- `docs/security/sandbox_backends.md` — related security docs

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-08-25 | Initial runbook created (S57 W1) | Kimi Code |
| TBD | Production flip date | TBD |
| TBD | OWASP sign-off date | TBD |
