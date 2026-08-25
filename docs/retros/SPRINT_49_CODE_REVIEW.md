# Sprint 49 Code Review (cycles 273-275) — 2026-08-25

> **Method**: Parent-agent review (swarm unreliable in S48, fell back to direct).
> **Scope**: 3 commits (BreakerPolicyAdapter, feature flag, JWT refresh integration).

## 0. Tool status

| Check | Result |
|---|---|
| pytest (4 files, 36 tests) | **36 passed in 1.76s** |
| ruff check | **PASS** (after auto-fix of 1 import sort) |
| mypy | **PASS** |

## 1. Verdicts

| Section | Verdict |
|---|---|
| **Security** | ✅ PASS — JWT validation, device_id binding, fail-closed on verifier unavailable, JWKS/RS256 support via existing JwtBackend |
| **Architecture** | ✅ PASS — Adapter pattern, graceful fallback, lazy imports, capability-checked facades |
| **Quality** | ✅ PASS — 36 tests cover all paths including bug fix verification |
| **Style** | ✅ PASS — Conventional commits, Russian-first comments, type hints |
| **Overall** | ✅ **APPROVED — ship-ready** |

## 2. Key findings

1. **Phase 2a foundation (cycle 273)**: BreakerPolicyAdapter provides clean
   bridge between middleware-style API and BreakerRegistry. 15 tests
   cover all paths including state translation (ClosedState → CLOSED,
   OpenedState → OPEN, HalfOpenedState → HALF_OPEN).

2. **Phase 2b foundation (cycle 274)**: `circuit_breaker_use_registry` flag
   declared with default OFF. Actual middleware wiring deferred to S50
   per ADR-0268 ceremony plan (middleware is security-critical).

3. **W3 JWT refresh integration (cycle 275)**: /auth/refresh endpoint now
   branches on `mobile_jwt_enabled` flag. JWT mode validates via
   MobileJwtVerifier; demo mode preserves backward compat.

4. **Bug found + fixed during testing (cycle 275)**: initial draft of
   refresh code was missing `from src.backend.core.config.features
   import feature_flags` line. This caused `feature_flags is not
   defined` NameError caught by try/except, making `mobile_jwt_on`
   always False. The DEBUG log technique caught it immediately.
   **Lesson**: always verify imports when copying patterns.

5. **Type safety**: mypy clean for both breaker.py (with Redis support)
   and breaker_policy_adapter.py.

## 3. Action items

### 3.1 Resolved

- [x] ruff import sort — auto-fixed
- [x] mypy typing — both files clean
- [x] Bug fix (missing import) — caught via debug logging
- [x] Test coverage — 36 tests for S49 changes

### 3.2 Carried over to S50

- [ ] S13 Phase 2b wiring: middleware uses adapter when flag ON
  (deferred per ADR-0268 ceremony plan)
- [ ] OWASP external sign-off for `mobile_jwt_enabled` flag flip
  (external dependency)
- [ ] S13 Phase 3 multi-pod integration tests
- [ ] Mobile JWT production enablement (after OWASP sign-off)

## 4. Files reviewed

| File | Lines | Status |
|---|---|---|
| `src/backend/core/resilience/breaker_policy_adapter.py` | 219 | NEW (cycle 273) |
| `tests/unit/core/resilience/test_breaker_policy_adapter.py` | 187 | NEW (cycle 273) |
| `src/backend/core/config/features/resilience.py` | +24 | MODIFIED (cycle 274) |
| `tests/unit/core/config/test_features_resilience.py` | +1, -1 | MODIFIED (cycle 274) |
| `src/backend/entrypoints/api/mobile/router.py` | +55 | MODIFIED (cycle 275) |
| `tests/unit/entrypoints/api/mobile/test_refresh_jwt_integration.py` | 209 | NEW (cycle 275) |

## 5. References

- `.kimi-code/skills/code-review/SKILL.md` — review methodology
- ADR-0267 — Sprint 49 plan
- ADR-0268 — S13 Phase 2 4-phase rollout plan
- ADR-0269 — S13 Phase 2a foundation
- Sprint 49 complete retro
