# ADR-0264: Sprint 46 Plan + Mobile JWT Phase 1 (cycle 261)

> **Status**: ACCEPTED.
> **Sprint**: 46 (S45 complete retro handoff).
> **Predecessor**: ADR-0262 (mobile JWT epic, current state).
> **Goal**: Wire JWT validation into mobile router (Phase 1).

## 0. Sprint 46 plan

| Week | Focus | Deliverable | Effort |
|---|---|---|---|
| **W1** | **Mobile JWT Phase 1** | `MobileJwtVerifier` class + feature-flag gated wiring in `_verify_mobile_token` | 2-3h |
| W2 | Mobile JWT Phase 2 | Token revocation (Redis jti) + per-device rate limit | 1-2h |
| W3 | Mobile JWT Phase 3 | Tests (unit + integration) + OWASP JWT checklist review | 2-3h |
| W4 | S-L7-5 RabbitMQ + consumer | Wire `extract_from_headers` into RabbitMQ producer/consumer + Kafka consumer | 2-3h |
| Final | Sprint 46 retro + S47 plan | Retro doc, plan ADR-0266 | 1h |

## 1. Phase 1 scope (this cycle)

### 1.1 Goal

Provide a JWT-based authentication path for mobile clients, gated by a new
feature flag `mobile_jwt_enabled` (default OFF). When OFF, current
fail-closed demo-flag behavior preserved. When ON (after proper Phase 2-3
security review), real JWT validation with mobile-specific claims.

### 1.2 New module: `src/backend/core/auth/mobile_jwt.py`

```python
class MobileJwtVerifier:
    """JWT verifier for mobile clients (ADR-0262 / ADR-0264).

    Wraps JwtBackend + validates mobile-specific claims:
    - device_id: UUID v4 format
    - tenant_id: matches TenantContext
    - jti: unique token identifier (for revocation in Phase 2)
    - iss: in configured whitelist
    - aud: matches configured audience
    - exp/nbf: validated by JwtBackend
    """

    def __init__(
        self,
        *,
        backend: JwtBackend,
        issuer_whitelist: list[str],
        audience: str,
    ) -> None: ...

    async def verify(self, token: str) -> MobileAuthContext:
        """Verify JWT and return mobile auth context with claims."""
```

### 1.3 Wiring in `entrypoints/api/mobile/router.py:_verify_mobile_token`

Add branch BEFORE demo flag check:
```python
if mobile_jwt_enabled:
    verifier = get_mobile_jwt_verifier()  # lazy init
    try:
        return await verifier.verify(token)
    except JwtVerificationError as exc:
        raise HTTPException(401, f"JWT verification failed: {exc}")
```

Demo flag path remains (for dev/staging without JWT).

### 1.4 Feature flag

Add `mobile_jwt_enabled: bool = False` to `core/config/features/infrastructure.py`.
Default OFF keeps current fail-closed production safety.

### 1.5 Why NOT full Phase 2/3 in this cycle

Per AGENTS.md Ponytail skill:
> Не упрощать: валидацию на границах доверия, обработку ошибок, меры
> безопасности, явно запрошенный пользователем функционал.

JWT validation IS a trust-boundary mechanism. Phase 1 ships the verifier
skeleton + flag-gated path. Phase 2-3 add revocation + rate limit +
OWASP review before merge to default-ON.

## 2. Verification slice

- [ ] `make lint && make type-check` passes
- [ ] New unit tests for `MobileJwtVerifier`: valid token, expired, malformed,
      wrong issuer, wrong audience, missing device_id, invalid device_id
- [ ] Existing mobile tests still pass (demo flag path unchanged)
- [ ] Default-OFF flag verified — no behavior change in production

## 3. References

- `docs/adr/0262-mobile-jwt-validation-epic-cycle-258.md` — epic plan
- `src/backend/core/auth/jwt_backend.py` — JwtBackend class
- `src/backend/entrypoints/api/mobile/router.py:60-117` — current fail-closed gate
- `docs/retros/SPRINT_45_COMPLETE_RETRO_2026-08-25.md` — handoff to S46
