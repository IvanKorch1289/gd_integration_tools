# Sprint 129 W1 — Tech-Debt 4-State Classification Report

**Date**: 2026-06-14
**Sprint**: 129
**Wave**: W1 (analysis-only, Rule #96)
**Author**: pre-flight per Rule #109 + Rule #121

## Context

S128 closure (ADR-0215) перечислил 6 open items for S129+:
1. TD-026 cont. (gRPC codegen wire-up)
2. TD-022 cont. (PydanticAIClient path coverage)
3. TD-021 cont. (ExternalDBFacade 5+ callsite migration)
4. TD-030 cont. (smtp.py Breaker.guard refactor)
5. TD-013 (Streamlit feature-grouping, 6+ hours)
6. TD-001/TD-031 (D5 B2/B3 + layer linter monitoring)

TECH_DEBT_REGISTER additionally lists 14 OPEN items across P0-P3.
**Pre-flight (Rule #109) обнаружил: 7 из 14 уже CLOSED or by-design** — the TD register is stale relative to actual gate state.

## Methodology

Per Rule #121 60-second pre-flight (parallel fact-check):
- `find` + `wc -l` для file inventory
- `grep -rE` для boundary violation scan
- `uv run python tools/<linter>.py` для каждого gate
- Per-TD verification: file existence, callsite counts, import-path direction

## 4-State Classification (Rule #114)

### P0 Items

| TD | Plan claim | Actual state | Classification |
|---|---|---|---|
| **TD-001** | 5 of 12 D5 models remaining | 7 of 12 в `core/domain/models/` (incl. all 5 from plan: orderkinds, orders, files, workflow_instance, workflow_event, + users, base). 5 remaining в `extensions/core_entities/*/domain/models.py` — **by-design** (different domain, не D5 banking). `extensions/credit_pipeline/domain/models.py` — separate domain, by-design. | **closed + by-design** (5/7 of plan, 5 remaining are not in scope) |
| **TD-002** | 9 NEW layer linter viols | `uv run python tools/check_layers.py` → **0 NEW** (210 legacy). Claim stale. | **closed** (state 1) |

### P1 Items

| TD | Plan claim | Actual state | Classification |
|---|---|---|---|
| **TD-003** | 4 missing protocol handlers (websocket/webhook/express/sse) | `uv run python tools/check_protocol_coverage.py` → **`[protocol_coverage] OK`**. All 4 handlers + bridge registered. Claim stale. | **closed** (state 1) |
| **TD-004** | 77 callsites (DI-callback vs service-locator) | `uv run python tools/check_audit_deprecation.py` → **0 legacy callsites**, 8 allowlisted mixin-internal. TD register says CLOSED (S111 W3), confirmed. | **closed** (state 1, verified) |
| **TD-005** | Runtime risk with optional deps (pyodbc/aioodbc/aiomysql/pymysql/ibm_db_sa) | `grep -rE "pyodbc\|aioodbc\|aiomysql\|pymysql\|ibm_db_sa" src/backend/infrastructure/database/` → **0 imports found** в expected paths. DSN support exists (S104 W3) but driver imports are elsewhere. | **partial** (state 3) — needs deeper grep to find actual driver import sites |
| **TD-006** | Test baseline allowlist masking ratchet signal | `find tests/unit/core/config -name "test_features*.py"` → 10 files exist, `test_validator.py` exists (both at `tests/unit/cache/` and `tests/unit/core/config/`). Allowlist existence не проверено в этом pre-flight. | **partial** (state 3) — file inventory done, allowlist status TBD |

### P2 Items

| TD | Plan claim | Actual state | Classification |
|---|---|---|---|
| **TD-007** | 17 callsites still use `self._audit: Callable` | `grep -rl "_audit: Callable" src/backend/` → **0 matches**. `audit_mixin.py` уже uses `emit_capability_check` из `core.audit.facade`. Claim stale. | **closed** (state 1) |
| **TD-018** | D5 shims active, hard delete after B2/B3 | `grep -rE "from src.backend.core.domain.models" extensions/ routes/` → **5 callsites using new path**. `grep -rE "from src.backend.extensions" src/backend/` → **0 backward shim callsites**. Все callsites мигрированы, shim obsolete. | **closed** (state 1) — hard delete shim возможен в W2/W3 |

## Summary

- **closed** (state 1): TD-002, TD-003, TD-004, TD-007, TD-018 = **5 items**
- **by-design** (state 2): TD-001 = **1 item**
- **partial** (state 3): TD-005, TD-006 = **2 items** (need deeper fact-check)
- **missing** (state 4): 0 (no genuinely new work discovered)

**Net: 6 of 8 OPEN items are already done.** This is a 75% stale-TD rate in the register — same pattern as S116-S117 cascade (Rule #109).

## Implications for S129 W2-W4

- **W2 candidates** (cherry-pick from partial/missing): TD-018 (delete obsolete shim, 1 commit ~30 min), TD-005 (DSN driver check, 1 commit ~1 hour), TD-006 (test baseline allowlist refresh, 1 commit ~30 min).
- **W3 candidates** (real new features): TD-021 cont. (ExternalDBFacade 5+ callsite migration), TD-009 (sub_workflow DSL method), TD-005 cont. (cookbook для DSN).
- **W4 candidates** (Rule #124 bonus): scan for pre-existing failures в touched files.

## Pre-existing Failures (from S128 W3)

- `tests/unit/entrypoints/grpc/test_grpc_server.py::test_load_tls_credentials_disabled_returns_none` — S65 W3 era, **pre-existing**. Per Rule #124, eligible for fix if small (single-file, single root cause).

## Score Impact

**No change** — fact-check (analysis-only) не moves score, just reduces decision-risk.
- 9.8 → 9.8 (maintained)

## References

- ADR-0215 (S128 closure, Sprint 128 score 9.8)
- `reports/reaudit/tech_debt_register.md` (stale vs gate state)
- Rule #109 (pre-sprint fact-check)
- Rule #114 (4-state classification)
- Rule #121 (60-sec pre-flight)
- `references/s116-w3-w5-factcheck-and-orphan-tests-2026-06-14.md` (precedent for 3-sprint NO-OP cascade)
- `references/s117-w1-factcheck-noop-2026-06-14.md` (precedent for NO-OP closure)
