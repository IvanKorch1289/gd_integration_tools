# ADR-0272: Mobile JWT Production Readiness Checklist (cycle 278)

> **Status**: TRACKED — required before `mobile_jwt_enabled` flag flip.
> **Method**: Direct check of all prerequisites from S46-S47-S49 work.
> **Conclusion**: All internal prerequisites met; external sign-off still BLOCKING.

## 0. Prerequisites checklist

| # | Prerequisite | Status | Source |
|---|---|---|---|
| 1 | MobileJwtVerifier implementation | ✅ DONE | S46 W1 (cycle 261) |
| 2 | Phase 2: RevocationStore + DeviceRateLimiter (in-memory) | ✅ DONE | S46 W2 (cycle 262) |
| 3 | OWASP JWT checklist (14/17 PASS) | ✅ DONE | S46 W3 (cycle 263) |
| 4 | Redis-backed RevocationStore | ✅ DONE | S47 W1 (cycle 266) |
| 5 | Redis-backed DeviceRateLimiter | ✅ DONE | S47 W1 (cycle 266) |
| 6 | Mobile router JWT path integration | ✅ DONE | S47 W2 (cycle 267) |
| 7 | /auth/refresh endpoint | ✅ DONE | S48 W2 (cycle 271) |
| 8 | /auth/refresh JWT path integration | ✅ DONE | S49 W3 (cycle 275) |
| 9 | mobile_jwt_enabled flag declared | ✅ DONE | S47 W2 (cycle 267) |

## 1. External dependencies (BLOCKING)

| # | Item | Owner | Status |
|---|---|---|---|
| **A** | **OWASP security team sign-off** | security@ | 🔴 EXTERNAL — not in our control |
| **B** | Mobile team confirmation: client uses Keychain (not localStorage) | mobile@ | 🔴 EXTERNAL |
| **C** | Refresh token rotation strategy | product@ | 🟡 DEFERRED — currently re-issue without revoking old |
| **D** | Production secret key distribution | devops@ | 🟡 DEFERRED — uses JwtBackend() placeholder |

## 2. OWASP deferred items (S46 ADR-0265)

| # | Item | Reason |
|---|---|---|
| 11 | Token sidejacking (fingerprint binding) | Deferred to Phase 4 (client cooperation) |
| 12 | Client-side storage | OUT OF BACKEND SCOPE |
| 13 | HTTPS only | INFRASTRUCTURE (deployment concern) |

## 3. Required for production flag flip

```python
# In production environment:
# 1. Set JWT_SECRET_KEY in secrets manager (NOT in code)
# 2. Set REDIS_URL for RevocationStore + DeviceRateLimiter
# 3. Set JWKS_URL (if using RS256 with key rotation)
# 4. Set FEATURE_MOBILE_JWT_ENABLED=true
# 5. Enable FEATURE_MOBILE_DEMO_AUTH_ENABLED=false (block demo)
# 6. Deploy + monitor for 1 week
# 7. If metrics OK → flip for all clients
# 8. If errors → revert flag, investigate
```

## 4. Rollback plan

If production issues detected:
1. Set FEATURE_MOBILE_JWT_ENABLED=false (instant rollback)
2. Fall back to demo flow (fail-closed 401 for non-demo clients)
3. Investigate logs + JWT verification errors
4. Fix and re-enable

## 5. Honest assessment

**Current state**: 9/9 internal prerequisites met.
**Blockers**: 2 external (OWASP sign-off, mobile team client confirmation)
**Deferrals**: 2 internal decisions (refresh rotation, secret distribution)

**Recommendation**: Surface items A and B to product owner for next sprint
planning. Do NOT flip flag without external sign-off.

## 6. References

- ADR-0262 — Mobile JWT epic
- ADR-0264 — Sprint 46 plan
- ADR-0265 — OWASP JWT checklist review
- `src/backend/entrypoints/api/mobile/router.py` — current JWT path
- `src/backend/core/auth/mobile_jwt.py` — verifier
- `src/backend/core/auth/mobile_jwt_redis.py` — Redis impls
