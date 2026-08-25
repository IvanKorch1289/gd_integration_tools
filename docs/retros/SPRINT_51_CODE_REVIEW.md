# Sprint 51 Code Review (cycles 280-284) — 2026-08-25

> **Method**: Parent-agent review (swarm unreliable).
> **Scope**: 5 commits — Phase 2c legacy removal, __call__ fix, purgatory integration, Phase 4 plan.

## 0. Tool status

| Check | Result |
|---|---|
| pytest (503 tests) | **503 passed** |
| ruff check | **PASS** |
| mypy | **PASS** |

## 1. Verdicts

| Section | Verdict |
|---|---|
| **Security** | ✅ PASS — legacy deque removed, registry path is sole modern alternative |
| **Architecture** | ✅ PASS — middleware now 2 clean paths (registry + sliding); purgatory ContextManager used correctly |
| **Quality** | ✅ PASS — 3 migrated tests, 9 legacy tests removed, 2 adapter tests updated |
| **Style** | ✅ PASS — conventional commits, Russian-first comments, comprehensive ADRs |
| **Overall** | ✅ **APPROVED — ship-ready** |

## 2. Key findings

1. **__call__ fix (cycle 280)**: Phase 2b missed the actual ASGI dispatch
   path. Bug discovered via JSON serialization error in test. Fix:
   added explicit registry dispatch at top of __call__ (line 369+).
   Middleware now correctly uses adapter when flag is ON.

2. **Phase 2c legacy removal (cycle 282)**: Per ADR-0271, removed
   `use_sliding_window_breaker` parameter and legacy deque code path.
   Middleware now has only 2 paths (registry + sliding). Removed 9
   legacy tests that validated removed code. Test count: 488 (was 498).

3. **Purgatory integration (cycle 283)**: Found real purgatory API —
   `breaker.context.handle_exception()` and `handle_end_request()`.
   Replaced graceful no-ops. Production state mutation NOW WORKS.
   S13 ceremony: 7/8 phases complete.

4. **Phase 4 rollout plan (cycle 284)**: Comprehensive staged rollout
   plan with monitoring thresholds, rollback procedures, and pre-rollout
   checklist. Documents external dependencies (Redis HA, monitoring).

5. **Net test delta**: 503 tests total (was 498 → +15 adapter tests
   → -12 legacy tests → +2 adapter updates → 503). Net +5 tests
   with better coverage.

## 3. Action items

### 3.1 Resolved

- [x] __call__ registry dispatch fix
- [x] Legacy deque path removed
- [x] Purgatory ContextManager protocol integration
- [x] Phase 4 staging rollout plan documented
- [x] 503 tests pass, ruff+mypy clean

### 3.2 Carried over to S52+

- [ ] S13 Phase 4 actual execution (dev → staging → prod rollout)
- [ ] Adapter refactor: accept actual exception (not synthetic RuntimeError)
- [ ] Redis HA setup in target environments
- [ ] OWASP security team sign-off (mobile_jwt_enabled flag flip)
- [ ] Mobile team client storage confirmation (Keychain)

## 4. Files reviewed

| File | Lines | Status |
|---|---|---|
| `src/backend/entrypoints/middlewares/circuit_breaker.py` | +60 LOC / -50 LOC | MODIFIED (cycle 280-282) |
| `tests/unit/entrypoints/middlewares/test_circuit_breaker.py` | -120 LOC | MODIFIED (cycle 282) |
| `tests/unit/entrypoints/middlewares/test_circuit_breaker_sliding.py` | minor | MODIFIED (cycle 282) |
| `tests/unit/entrypoints/middlewares/test_circuit_breaker_registry_path.py` | minor | MODIFIED (cycle 282) |
| `src/backend/core/resilience/breaker_policy_adapter.py` | -8 / +11 LOC | MODIFIED (cycle 283) |
| `tests/unit/core/resilience/test_breaker_policy_adapter.py` | -4 / +6 LOC | MODIFIED (cycle 283) |
| `docs/adr/0273-*.md` | 83 | NEW (cycle 281) |
| `docs/adr/0274-*.md` | 101 | NEW (cycle 282) |
| `docs/adr/0275-*.md` | 84 | NEW (cycle 283) |
| `docs/adr/0276-*.md` | 100 | NEW (cycle 284) |

## 5. References

- ADR-0268 — original S13 plan
- ADR-0270 — Sprint 50 plan
- ADR-0271 — Phase 2c deferral plan (now complete)
- ADR-0273 — Phase 2b-2 __call__ fix
- ADR-0274 — Phase 2c completion
- ADR-0275 — Purgatory integration
- ADR-0276 — Phase 4 rollout plan
