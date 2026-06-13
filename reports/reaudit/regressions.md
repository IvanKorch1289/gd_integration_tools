# Regressions & Newly-Introduced Issues

> Verified against master HEAD (commit `423cdadc`).

---

## R1. Core linter — 9 NEW violations (post-S93 work)

**Introduced by:** S103 W3 (audit facade) + S101 W1 (cdc registry)

| File | Imports | Status |
|------|---------|--------|
| `src/backend/core/audit/facade.py` | `src.backend.services.audit.audit_service` | core → services violation |
| `src/backend/core/cdc/registry.py` | `src.backend.infrastructure.cdc.cdc_client_adapter` | core → infrastructure violation |
| ... 7 more | ... | (per `check_layers.py` output) |

**Severity:** P0 (recently introduced, contrary to V22 layer rule)
**Fix:** Add `core/audit/` and `core/cdc/registry.py` to legacy allowlist OR re-export via indirection.

## R2. Extensions linter — 39 NEW violations (D5 B2/B3 backlog)

**Introduced by:** Pre-existing (D5 split-brain known since S94 W1)

| Pattern | Count |
|---------|-------|
| `extensions → infrastructure.database.models.*` (Risk B/C) | 5+ |
| `extensions → infrastructure.repositories.base` | 3+ |
| `extensions → infrastructure.database.session_manager` | 2+ |
| `extensions → services.*` | 11+ |
| `extensions → schemas.*` | 2+ |
| `extensions → entrypoints.*` | 5+ |
| `extensions → core (other than core.domain.models)` | misc |

**Severity:** P0 (D5 backlog)
**Fix:** D5 B2 (S106 W3-W4) + D5 B3 (S106 W5) — sprint plan covers.

## R3. Protocol coverage gate — FAIL (5 missing bridges)

**Verified via:** `tools/check_protocol_coverage.py` (current output)

```
[protocol_coverage] FAIL
  - missing bridge module: src/entrypoints/_action_bridge.py
  - ws: missing file src/entrypoints/websocket/ws_handler.py
  - webhook: missing file src/entrypoints/webhook/handler.py
  - express: missing file src/entrypoints/express/router.py
  - sse: missing file src/entrypoints/sse/handler.py
  - missing src/dsl/commands/setup.py (Tier 1 setup)
```

**Caveat:** `_action_bridge.py` FILE EXISTS (per `ls src/backend/entrypoints/`), but coverage check complains. This suggests:
- Coverage check expects a different file name
- OR existing `_action_bridge.py` doesn't have the expected surface
- OR coverage check is itself outdated

**Severity:** P1
**Fix:** Sprint 2 — investigate `_action_bridge` first (likely false positive), then add 4 missing handlers + `dsl/commands/setup.py`.

## R4. Pre-existing test failures — 572 in baseline

**Verified via:** `git stash` + run + unstash (proves pre-existing, not my regressions)

**Affected areas (master HEAD baseline):**
- `tests/unit/core/config/test_features_sprints_24_27.py` — TestSprints2427FlagsClass + composition tests
- `tests/unit/core/config/test_validator.py` — TestFeatureFlagDependencyUnmet
- 70 collection errors in DSL processor tests (registry conflicts)

**Severity:** P2 (signal masking)
**Fix:** Sprint 2 — add baseline allowlist so ratchet has clear signal.

## R5. S62 W2 (subagent) — TypeError pre-existing in test_smart_session_manager_wire

**Verified via:** `git stash` + run (proves pre-existing)

```
tests/unit/infrastructure/database/test_smart_session_manager_wire.py::test_bundle_carries_replica_session_maker
TypeError: DatabaseBundle() takes no arguments
```

**Severity:** P3
**Fix:** Sprint 3 (opportunistic).

## R6. S62 W2 — DSL processor collection errors (3 files)

**Verified via:** `git stash` + run

```
ERROR tests/unit/dsl/engine/processors/test_llm_structured.py - src.backend.dsl.registry.errors.ProcessorConflictError: Processor 'core:llm_structured' already registered
ERROR tests/unit/dsl/orchestration/test_s56_w2_airflow_operators.py
ERROR tests/unit/dsl/processors/test_idp_pipeline_processor.py
```

**Severity:** P3
**Fix:** Sprint 3 (idempotent registry decorator test setup).

## R7. Post-S106 W1 — `__all__` bug в base.py

**Fixed in S106 W1** (commit included):
- `Base` symbol was missing from `__all__` in `core/domain/models/base.py` — masked by direct attribute access in pre-shim code, but broke shim `import *` behavior.
- Fix: added `"Base"` to `__all__` tuple.
- Risk: any code that did `from src.backend.core.domain.models.base import Base` (without explicit import) would have failed. Caught by `test_audit_versioning.py` during S106 W1.

**Severity:** N/A (fixed)

## R8. Audit facade growth — 74 → 394 LOC

**Introduced by:** S103 W3 (74 LOC) + S106 W2 (320 LOC, 7 helpers)

**Severity:** P3 (architectural smell, not bug)
**Fix:** Sprint 3 — split `facade.py` → `facade/{authorization,waf,capability,secret_rotation,ai_workspace,safe,banking}.py` per S106 W2 helper taxonomy.

---

## Regressions NOT Observed

- ✅ Ratchet: 0 NEW violations (allowlist 1636, current 1636)
- ✅ Stdlib logging: 0 violations (8 legitimate uses locked)
- ✅ Docstring gate: paths extended, no path regression
- ✅ Layer independence: no NEW violations in services/infrastructure/dsl (only core + extensions)
- ✅ DSL: 0 broken methods (verified by grep of builder methods)
- ✅ Tests: 0 NEW failures introduced by S106 W1/W2 (delta 0)
- ✅ Public API: all changes additive (no breaking changes since S99)

---

## Severity Triage

| ID | Severity | Sprint to fix |
|----|----------|---------------|
| R1 | P0 | Sprint 1 |
| R2 | P0 | Sprint 1 (W3-W4) + Sprint 1 (W5 closure) |
| R3 | P1 | Sprint 2 |
| R4 | P2 | Sprint 2 (baseline allowlist) |
| R5-R6 | P3 | Sprint 3 (opportunistic) |
| R7 | N/A | Done in S106 W1 |
| R8 | P3 | Sprint 3 (opportunistic) |
