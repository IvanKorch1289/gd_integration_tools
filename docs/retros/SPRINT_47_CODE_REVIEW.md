# Sprint 47 Code Review (cycles 266-268) — 2026-08-25

> **Method**: Swarm review via subagent + parent-agent finalization.
> **Scope**: `mobile_jwt_redis.py` (cycle 266), `test_mobile_jwt_redis.py` (cycle 266),
> `test_mobile_router_jwt_integration.py` (cycle 267), ADR-0266 (cycle 268).
> **Reviewer**: explore subagent (read-only analysis) + parent agent fixes.

## 0. Tool status

| Check | Result |
|---|---|
| pytest 13 unit + 6 integration | **19 passed in 3.54s** |
| ruff check `mobile_jwt_redis.py` | **PASS** (after auto-fix of I001) |
| mypy `mobile_jwt_redis.py` | **PASS** (after `_get_client()` await fix) |

## 1. Verdicts

| Section | Verdict |
|---|---|
| **Security** | ✅ PASS — input validation, TTL-aligned revocation, no PII in Redis, fail-open documented |
| **Architecture** | ✅ PASS — Protocol-conformant, lazy-imports avoid cycles, DI-friendly, configurable prefixes |
| **Quality** | ✅ PASS — 19 tests, real-assertion quality, isolation via monkeypatch/AsyncMock, ADR-0265 §2 #3 fulfilled |
| **Style** | ✅ PASS (after fixes) — ruff clean, mypy clean, docstrings present |
| **Overall** | ✅ **APPROVED — ship-ready** |

## 2. Key findings

1. **All 19 tests pass** — full router→JWT→response flow covered with mocked
   JwtBackend (no live Redis needed).
2. **Fail-open on Redis outage is intentional + documented** — acceptable
   for mobile degraded mode; caller can layer fail-closed policy.
3. **TTL = max(1, exp - now)** prevents unbounded key growth; aligns cleanup
   with JWT expiry.
4. **ADR-0266 correctly scoped** — S13 CB Redis ≠ S47 Phase 2 (JWT revoke/RL);
   DECLINE does not block S47 completion.
5. **Two minor non-blocking issues resolved** — auto-fixable ruff I001 +
   mypy strict-mode typing on `_get_client()` (was awaiting a sync factory).

## 3. Action items

### 3.1 Resolved in this review cycle

- [x] ruff I001 — auto-fixed by `ruff check --fix`
- [x] mypy typing on `_get_client()` — fixed by removing `await` from
      sync `get_redis_client()` call. Documented in docstring.
- [x] Test mock signatures updated — `_unavailable` / `_broken_get` /
      `_get_client` changed from `async def` to `def` (since `get_redis_client()`
      is sync). 13 tests still pass.

### 3.2 Carried over (optional)

- (Optional) Document/align asymmetry in `revoke()`:
  - line 95 (`is_revoked`) swallows Redis unavailable (fail-open)
  - line 109 (`revoke`) re-raises on write error

  Both are intentional (read fail-open, write fail-loud), but a docstring
  comment could clarify the asymmetry. **NOT blocking**.

## 4. Files reviewed

| File | Lines | Status |
|---|---|---|
| `src/backend/core/auth/mobile_jwt_redis.py` | 215 | PASS (after fixes) |
| `tests/unit/core/auth/test_mobile_jwt_redis.py` | 187 | PASS |
| `tests/unit/entrypoints/api/mobile/test_mobile_router_jwt_integration.py` | 171 | PASS |
| `docs/adr/0266-s13-circuit-breaker-redis-still-declined-cycle-268.md` | 108 | PASS |

## 5. References

- `.kimi-code/skills/code-review/SKILL.md` — review methodology
- ADR-0265 — OWASP JWT checklist (security context)
- ADR-0266 — S13 DECLINED (architecture decision context)
- Sprint 47 complete retro — handoff to S48
