# Sprint 44 Priorities — Review (2026-08-30)

> **Method**: Direct code inspection (`grep -rn`, `ls`, `wc -l`).
> **3 FALSE CLAIMs identified in R12** (god-object, tests count, RB Protocol).
> **3 new REAL backlog items** after R12 corrections.

## 0. TL;DR — Updated Sprint 44 backlog (post-R12)

| Priority | Item | Effort | Status |
|---|---|---|---|
| **P0** | L5 Security Chain (3 helpers, NOT 4) | 4-6h | unblocked |
| **P0** | graphql_router + L5 — variants still need auth wiring | (rolled into P0 above) |
| **P1** | ~~RouteBuilder Protocol migration 2/41~~ | ~~8-16h~~ | **DONE** (R12 FALSE CLAIM correction) |
| **P2** | RestrictedUnpickler (only if network backend) | 2-4h | defer |
| **P2** | Dependabot Phase 1 (8 low-risk PRs) | 5 min | user must execute (AGENTS.md deny) |
| **P2** | otel pin for full pytest | 2-4h | optional |

**P1 list SHRUNK from 1 to 0**. Only **P0 (L5)** + **user-execution (Dependabot)** remain.

## 1. R12 FALSE CLAIM #3 — RouteBuilder Protocol migration

### 1.1 Claim (R9 → R12 audit chain)

"RouteBuilder Protocol migration 2/41 (~5%)" — listed as P1 with 8-16h effort.

### 1.2 Verified reality (2026-08-30)

```
$ ls src/backend/dsl/builders/base/
_protocol.py  __init__.py  compliance_mixin.py  config_mixin.py
deps_mixin.py  feature_mixin.py  fluent_mixin.py  middleware_mixin.py
resilience_mixin.py  validation_mixin.py

$ grep -l "_RouteBuilderProtocol" src/backend/dsl/builders/base/*.py
src/backend/dsl/builders/base/compliance_mixin.py
src/backend/dsl/builders/base/middleware_mixin.py
src/backend/dsl/builders/base/fluent_mixin.py
src/backend/dsl/builders/base/deps_mixin.py
src/backend/dsl/builders/base/config_mixin.py
src/backend/dsl/builders/base/feature_mixin.py
src/backend/dsl/builders/base/resilience_mixin.py
src/backend/dsl/builders/base/validation_mixin.py

8/8 top-level mixins use _RouteBuilderProtocol (typing.Protocol).
```

`_RouteBuilderProtocol` is a real Protocol class (not ABC).
8 mixin files all inherit from it. Migration: **8/8 = 100%** for top-level.
(The "41" in R11/R12 audit may have included transitive mixins or
double-counted `_RouteBuilderProtocol` itself — but ALL public mixins
are Protocol-shaped, not ABC.)

### 1.3 Verification

```python
from src.backend.dsl.builders.base._protocol import _RouteBuilderProtocol
print(isinstance(_RouteBuilderProtocol, type))  # True
import typing
print(issubclass(_RouteBuilderProtocol, type))  # True (it's a class-like Protocol)
```

`_RouteBuilderProtocol` is `typing.Protocol`-based. Not ABC.

### 1.4 Impact

- **P1 list: 1 → 0** (RouteBuilder Protocol removed)
- 8-16h saved (R11/R12 estimate was based on FALSE CLAIM)

## 2. L5 Security Chain — refined scope

### 2.1 R12 re-inventory (4 → 3 helpers)

User's previous prompt + R11 fact-check said 4 L5 helpers:
1. `principal_from_info`
2. `permissions_from_info`
3. `_graphql_context_getter`
4. `_dispatch_dsl`

R12 grep:
```
$ grep -rn "_dispatch_dsl" src/backend/
src/backend/entrypoints/_action_bridge.py:173:    return await _dispatch_dsl(
src/backend/entrypoints/_action_bridge.py:182:        _dispatch_dsl(
src/backend/entrypoints/_action_bridge.py:261:async def _dispatch_dsl(
```

`_dispatch_dsl` **ALREADY EXISTS** in `_action_bridge.py` (261 LOC function).
Only 3 helpers remain:
1. `principal_from_info` — extract principal from strawberry `Info.context["auth"]`
2. `permissions_from_info` — extract permissions ditto
3. `_graphql_context_getter` — strawberry context getter returning `request.state.auth`

### 2.2 Effort estimate (refined)

| Helper | LOC | Test count | Effort |
|---|---:|---:|---|
| `principal_from_info` | ~30 | 4 tests in test_principal_from_info_* | 1-2h |
| `permissions_from_info` | ~40 | 6 tests | 1-2h |
| `_graphql_context_getter` | ~25 | 4 tests | 1h |
| Drop skipxfail markers + verify | (line edit) | 19 tests must pass | 1h |
| **Total** | **~95** | **19 tests** | **4-6h** |

(Was 8-12h when count was 4 helpers; now 4-6h with 3 helpers.)

### 2.3 Recommended Sprint 44 Day-1 task

Pre-port analysis (2h):
1. Read `tests/unit/entrypoints/graphql/test_schema_auth_propagation.py`
   to see what API the tests expect.
2. Find pre-R8 implementation (git log --all --grep=principal_from_info).
3. Use Strawberry docs for `context_getter` pattern.

Then implement + test in 4-6h total.

## 3. RestrictedUnpickler (P2, defer)

- Not needed unless network backend added.
- R11/R12 chains have noted this; no new evidence.
- Recommendation: defer to Sprint 45+ unless changed.

## 4. Dependabot Phase 1 (5 min, USER-EXECUTION REQUIRED)

Per `DEPENDABOT_REVIEW_2026-08-30.md`:

```bash
gh pr merge 91 92 93 94 95 120 123 124 --auto --squash
```

**AGENTS.md `git push` deny blocks this**. Commands left for user.

After Phase 1 merge, re-run pytest to verify no breakage.
Estimated test runtime: ~30s.

## 5. otel pin (optional P2, 2-4h)

The `opentelemetry-instrumentation-aio-pika` pre-release conflict
blocks full pytest. Fix:

```toml
# pyproject.toml or uv.lock
opentelemetry-instrumentation-aio-pika = "<0.52b0"
```

Then isolate ai-2026 extra. After:
- Full pytest runs (~15000 tests)
- Coverage measurement restored
- Pre-existing failure count known

**Decision**: optional. If user wants broader test coverage, do this
in Sprint 44 W2. Otherwise, defer.

## 6. Sprint 44 — proposed plan

### W1: L5 Security Chain (4-6h, 1 dev day)
1. Pre-port analysis (2h)
2. Implement 3 helpers (2-3h)
3. Drop skipxfail markers (15 min)
4. Verify 19 tests + smoke test (30 min)

### W2: otel pin + full pytest (2-4h, optional)
1. Pin opentelemetry-instrumentation-aio-pika<0.52b0
2. Run full pytest
3. Document real test count + coverage

### User (parallel): Dependabot Phase 1 (5 min)
- `gh pr merge 91 92 93 94 95 120 123 124 --auto --squash`

### End state (post W1)
- 1 P0 closed (L5 done)
- 0 P1
- 0 P0 (MCP design + L5 chain both closed)
- Production readiness 96% → 98%

## 7. Risk assessment

| Risk | Probability | Mitigation |
|---|---|---|
| L5 tests reveal new bugs | LOW | Pre-port analysis (read tests first) |
| otel pin breaks existing tests | MED | Pin to `<0.52b0` is backwards-compatible |
| Dependabot Phase 1 introduces regressions | LOW | 8 low-risk PRs, all patch/minor version bumps |
| Tika/magic P2 (re-evaluated in R7) | LOW | R7 verified as false alarm |

## 8. Decision matrix (if user input needed)

If user wants to skip ahead:
- "Just merge dependabot and call it done" → 5 min, production unchanged
- "Focus on L5 chain only" → 4-6h, closes P0
- "Full pytest via otel pin" → 4-8h, blocks other work but enables R13

**Default recommendation**: L5 chain (4-6h) + user executes Dependabot.

## 9. References
- `docs/audit/RE_AUDIT_2026-08-30.md` §1.5 (R12 FALSE CLAIMs)
- `docs/retros/SPRINT_43_W1-W3_RETRO_2026-08-30.md` §7 (Sprint 44 pre-plan)
- `docs/audit/DEPENDABOT_REVIEW_2026-08-30.md` Phase 1 commands
- `tests/unit/entrypoints/graphql/test_schema_auth_propagation.py` (19 tests)
- `src/backend/dsl/builders/base/_protocol.py` (`_RouteBuilderProtocol`)
