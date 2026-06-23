# Documentation Audit — S168 W14

**Date**: 2026-06-23
**Scope**: CHANGELOG.md, ADR INDEX, recent sprint documentation

---

## CHANGELOG.md — Status: ✅ ACCURATE

- S20-S45 entries (dated 2026-06-17 to 2026-06-22): ✅ Matches git log
- Content corresponds to actual commits (verified against `git log --oneline -30`)
- Sprint labels follow pattern: `S{session_number}` — matches internal sprint convention
- All entries have Rule references (Rule 3, Rule 8, etc.)

### Gap Found

**S168 W14 P2-10 commit** (`0ecd00f`): filter schemas importlib fix — NOT in CHANGELOG.
- Fixes ModuleNotFoundError for 4 filter.py files
- Backend verified: 130 actions, 130 DSL routes
- Needs CHANGELOG entry + ADR closure

---

## ADR INDEX — Status: ✅ COVERED (with minor gaps)

| ADR | Topic | Status | Notes |
|-----|-------|--------|-------|
| ADR-0245 | S168 Delta Closure | CLOSED | Covers S168 W11 W12 W13 — NOT W14 |
| ADR-0246 | S30 Security Patch | CLOSED | Dependabot 7 vulns |
| ADR-0247 | S169 W2 Feature Pack | CLOSED | RLM, DI Scope, Tool Policy |

### Gap Found

**S168 W14** has no ADR. Session commits from S168 W14:
- `0ecd00f` (S168 W14 P2-10): filter importlib fix → needs ADR or CHANGELOG entry
- `b5203f0` (fix ops): Python-2 except syntax fix → needs CHANGELOG entry
- `3f06315` (refactor deep-research): dispatch dict test + Python-2 except
- `22fe381` (refactor deep-research): 6 module improvements
- `93a14a2` (fix s3-followup): agent_graph isolated flag

**Action**: Add S168 W14 entry to CHANGELOG with scope summary.

---

## Pre-existing Issues (Not in Scope for This Session)

### Orphaned Test Files (8 collection errors)

These tests reference deleted/moved modules — pre-existing state from working tree:

| Test File | Missing Module | Sprint of Origin |
|-----------|---------------|-----------------|
| `test_s57_w1_datetime_utils.py` | `src.backend.core.util.datetime_utils` | S57 W1 |
| `test_s57_w3_json_utils.py` | `src.backend.core.util.json_utils` | S57 W3 |
| `test_yaml_io.py` | Workflow YAML module (moved) | S4 |
| `test_order_tenant_mixin.py` | `core.domain.models.order_tenant_mixin` | S106 |
| `test_audit_versioning_user_integration.py` | Unknown | Unknown |
| `test_dsl_editor_helpers.py` | Schema registry (moved) | S30 |
| `test_region_routing.py` | Region routing module | S107 |
| `test_orders_saga.py` | Orders saga (moved) | S4 |

**Action**: These tests need either:
1. Restore the modules they reference (if still needed)
2. Delete the tests (if functionality moved/removed)
3. Update import paths (if modules were moved, not deleted)

### Test Failures (3 failures, pre-existing)

| Test | Failure | Sprint |
|------|---------|--------|
| `test_get_ad_client_caches_instance` | `AdDirectoryClient` not in `ldap_client_factory` | S43 |
| `test_auth_methods_with_ldap_enabled` | Same | S43 |
| `test_module_exposes_all_bootstrap_helpers` | `lifecycle.v11` not found | S45 |

**Action**: Either restore the missing symbols or delete the tests.

---

## Sprint Label Consistency

Git log shows inconsistent sprint labels:
- Modern format: `fix: S168 W14 P2-10`, `feat(s6-final)` ✅
- Old format: `fix(s36-w6)`, `refactor(s44-w3)` ✅
- Very old: `feat(s1)`, `feat(s3,s7,s8)` ✅ (S1-S8 are real old sprints)
- Inconsistent: `chore: local dev env tweaks` (no sprint label)

**Status**: Most recent commits have sprint labels. Minor gap: some old commits lack labels.

---

## Recommendations

1. **S168 W14 CHANGELOG entry**: Add entry documenting filter schemas fix + backend startup resilience
2. **Orphaned tests**: Triage 8 collection errors — restore, delete, or migrate
3. **ADR-0245 extension**: Consider adding S168 W14 to ADR-0245 if scope is related
4. **Healthchecks**: Add to `app` and `workflow-worker` in docker-compose (see `docs/ops/docker-compose-gap.md`)
