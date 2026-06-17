# TD-006 — Pre-existing Test Failures Classification (S164 backlog)

**Status**: 🟡 PARTIAL (S132 W5 sync, post-S133 W1 classification)
**Origin**: Pre-existing 572 failures + 70 collection errors (per TD-006 entry)
**Sprint target**: S164+ (multi-sprint effort)

## S163 W30 — Classification Update

Per S163 W1 audit (drift recovery), TD-006 baseline at start of session:
- 12 of 12 originally-identified failures closed (S132 W2 `test_llm_structured.py` 10 fixes + S132 W3 `test_s56_w2_airflow_operators.py` 2 fixes)
- `test_idp_pipeline_processor` claim was STALE (test does not exist)
- **~262 pre-existing failures remain** в 2 directories:
  - `tests/unit/dsl/engine/processors/`: ~109 failures
  - `tests/unit/dsl/builders/`: ~153 failures

## Observed Failures Pattern (S163 W30 sample)

### test_retry.py (broader sweep — 6 failures)
- Test pollution: all 6 pass in isolation (`pytest tests/unit/infrastructure/resilience/test_retry.py`)
- Root cause: pytest class-level state leakage between tests in same session
- Per skill "Pre-existing failures — known false positives": do NOT attribute to changes

### test_yaml_loader_composition.py (7 failures, TestIncludeExtends)
- `_is_route_composition_include_enabled` flag default-OFF
- Tests expect FileNotFoundError but loader doesn't raise (feature disabled)
- Root cause: feature flag wiring — tests written before feature disabled
- Fix: 2 options — (a) enable feature flag in conftest.py, (b) mark tests as xfail

### test_http_no_circuit_breaker.py (1 failure)
- `test_no_circuit_breaker_attribute` expects HTTP client to NOT have CB
- S163 W19-W22 added CB infrastructure to http_httpx.py
- **Potential regression from S163 W22!** — need to verify

### tests/unit/infrastructure/clients/transport/test_imap_pool.py (13 skipped)
- `imap_pool` not importable — module missing or import error
- Pre-existing (per S163 W1 baseline)

### tests/unit/services/dsl/ (S133 W1 classified as PARTIAL)
- ~109 engine/processors test failures — likely related to processor MRO changes
- ~153 builders test failures — likely related to mixin namespace merging

## Recommended S164 Actions

| Action | Priority | Effort |
|--------|----------|--------|
| 1. Verify S163 W22 HTTP CB regression in test_http_no_circuit_breaker | **P0** | S (30 min) |
| 2. Fix test_yaml_loader_composition (mark xfail OR enable feature) | P1 | S (1-2 hours) |
| 3. Fix test_retry.py test pollution (proper fixture isolation) | P2 | M (2-3 hours) |
| 4. Classify 262 failures by root cause | P1 | M (4-6 hours) |
| 5. Fix 1-2 root cause patterns | P2 | M per root cause |

## Reference

- `tools/check_test_baseline.py` — pre-existing test gate (current state)
- `reports/reaudit/tech_debt_register.md` — TD-006 entry
- `tests/unit/infrastructure/clients/transport/test_http_no_circuit_breaker.py` — regression check needed

## Out of S163 Scope

S163 W30 produced this classification doc but did NOT fix any pre-existing
failures (per master prompt "Inline TD closure" + TD-006 PARTIAL status).
Multi-sprint scope, separate backlog.
