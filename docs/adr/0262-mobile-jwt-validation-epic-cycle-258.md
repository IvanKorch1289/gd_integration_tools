# ADR-0262: Mobile JWT Validation Epic — Current State + Plan (cycle 258)

> **Status**: PROPOSED.
> **Method**: Direct inspection of `entrypoints/api/mobile/router.py:70-117`
> and `core/auth/jwt_backend.py:1-461`.
> **Context**: 2 explicit TODO comments in mobile router flag real auth gap
> (no JWT validation in production path). This ADR records current safety
> posture and implementation plan.

## 0. TL;DR

| Aspect | Current state | Target |
|---|---|---|
| Production auth on `/api/v1/mobile/*` | **FAIL-CLOSED** via `mobile_demo_auth_enabled` feature flag (default OFF) | Real JWT validation with mobile-specific claims (device_id, tenant_id) |
| Demo flag ON (dev/staging only) | Demo token format `mobile:<user_id>:<token>` | (unchanged for dev) |
| Risk in production | **LOW** — flag is OFF by default, mobile clients get 401 | LOW (after JWT wired) |
| Implementation effort | n/a | 4-8h with security review |

## 1. Current state (verbatim from source)

### 1.1 `entrypoints/api/mobile/router.py:70-117`

```python
"""
D-AUDIT-9101 fix (cycle 91, API-P0-005): добавлен fail-CLOSED gate
на feature flag ``mobile_demo_auth_enabled``. В production
(default OFF) ЛЮБОЙ mobile:* токен → 401, потому что demo
format не валидируется (fail-OPEN vulnerability). В dev_light
/ dev / staging (flag ON) — старое поведение сохранено для
удобства разработки.

Production: JWT validation с mobile-specific claims (device_id, tenant_id) — TODO.
For demo (flag ON only): simple bearer format ``mobile:<user_id>:<token>``.
"""

# D-AUDIT-9101: demo-auth fail-CLOSED gate.
try:
    from src.backend.core.config.features import feature_flags
    demo_auth_enabled = bool(getattr(feature_flags, "mobile_demo_auth_enabled", False))
except Exception:
    demo_auth_enabled = False  # fail-CLOSED

if not demo_auth_enabled:
    # Real JWT validation ещё не реализован (TODO epic), поэтому
    # единственный fail-closed вариант — 401 на любой mobile:* токен.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Mobile demo auth disabled (FEATURE_MOBILE_DEMO_AUTH_ENABLED=false). "
            "JWT-based mobile auth not yet implemented — production access requires "
            "explicit feature flag enable or proper JWT validation."
        ),
    )
```

### 1.2 Risk assessment

**Current risk level**: **LOW** for production.

Justification:
- Feature flag `mobile_demo_auth_enabled` defaults to **OFF**
- When OFF: every `mobile:*` token returns 401
- When ON (only dev/staging): demo format accepted but limited scope
- Even if a malicious token reaches mobile endpoint in production,
  the feature flag gate prevents authentication
- No mobile business endpoints expose data without auth (verified by
  `mobile_demo_auth_enabled` flag check at the route entry point)

**Known limitations**:
1. No way for legitimate mobile clients to authenticate in production
2. Mobile API surface effectively unavailable in prod
3. Demo flag must be manually enabled per environment

## 2. Why NOT implement JWT in this cycle

Per AGENTS.md Ponytail skill:
> Не упрощать: валидацию на границах доверия, обработку ошибок,
> предотвращающую потерю данных, меры безопасности, явно запрошенный
> пользователем функционал, архитектурные правила проекта.

JWT validation IS security-critical and NOT a quick add. Required components:
- Token signature verification (RS256 or HS256)
- Expiration (`exp`) and `nbf` checks
- Issuer (`iss`) and audience (`aud`) validation
- Mobile-specific claims: `device_id`, `tenant_id` (multi-tenant)
- Token revocation list (Redis-backed)
- Rate limiting per device_id (prevent brute force)
- OWASP JWT security checklist review

**Estimated effort**: 4-8 hours implementation + 2-4 hours security review
(OWASP JWT cheat sheet). Cannot be safely done in a 1-session sprint slice.

## 3. Implementation plan (S46+ dedicated cycle)

### 3.1 Phase 1 — JWT infrastructure wiring (2-3h)

- [ ] Define `MobileJwtVerifier` in `core/auth/mobile_jwt.py` (new file)
- [ ] Use existing `JwtBackend.decode()` for signature + expiration
- [ ] Add mobile-specific claims validator:
  - `device_id` (UUID v4 format)
  - `tenant_id` (matches TenantContext)
  - `iss` whitelist (e.g., `gd-mobile-prod`, `gd-mobile-staging`)
  - `aud` = `gd-mobile-api`
- [ ] Wire into `entrypoints/api/mobile/router.py` BEFORE the demo flag check
  (JWT path takes precedence over demo flag when configured)

### 3.2 Phase 2 — Revocation + rate limiting (1-2h)

- [ ] Add `token_revocation_check` Redis lookup (cached for 60s)
- [ ] Per-device rate limit (existing `core.api.rate_limit` facade)
- [ ] Audit log entry per mobile auth attempt (success/failure)

### 3.3 Phase 3 — Tests + security review (2-3h)

- [ ] Unit tests: valid token, expired, revoked, malformed, wrong issuer
- [ ] Integration tests: full mobile route flow
- [ ] OWASP JWT security checklist review (mandatory before merge)
- [ ] Penetration testing checklist (deferred to security team)

### 3.4 Phase 4 — Deprecate demo flag (1h)

- [ ] Add deprecation warning to `mobile_demo_auth_enabled`
- [ ] Plan removal in S48 (2 cycles after JWT ships)
- [ ] Update demo docs

## 4. Honest current state — acceptable for production?

**Yes**, with the following operational caveat:

| Environment | Mobile API | Acceptable? |
|---|---|---|
| Production | Locked (401) | ✅ YES (no data exposure risk) |
| Staging | Demo flag OFF → 401, ON → demo format | ✅ YES (intentional for testing) |
| Dev | Demo flag ON → demo format | ✅ YES (intended dev convenience) |
| Dev_light | Demo flag ON → demo format | ✅ YES (intended) |

**Operational recommendation**: mobile clients in production should be
told "use web/standard auth until JWT ships in S46". Until then, no
mobile client SHOULD exist in production environment.

## 5. References

- `src/backend/entrypoints/api/mobile/router.py:70-117` — fail-closed gate
- `src/backend/core/auth/jwt_backend.py:1-461` — existing JWT infrastructure
- `src/backend/core/config/features/infrastructure.py` — `mobile_demo_auth_enabled` flag
- `docs/adr/0259-audit-claims-factcheck-cycle-249.md` — sister fact-check ADR
- OWASP JWT Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html
