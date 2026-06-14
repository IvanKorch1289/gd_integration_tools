# S112 — Reaudit summary (post-S111, W1-W3 closure)

**Date:** 2026-06-14
**Source:** S111 W5 ADR-0197 backlog
**Sprint:** S112 (4 working waves + W5 closure)
**Status:** W1-W3 DONE, W4 in progress, W5 pending

---

## Pre-S112 baseline (from S111 W5 ADR-0197)

| Metric | Value | Source |
|---|---|---|
| Stale allowlist entries | 264 (41 default + 223 extensions) | Pre-S112 scan |
| NEW core violations (--strict vs allowlist) | 3 | Pre-S112 scan |
| NEW extensions violations (--strict vs allowlist) | 10 | Pre-S112 scan |
| Total actionable | 13 | S112 W2 triage |

---

## S112 W1: --prune-allowlist (commit `e4a79e87`)

**Tool change:** `tools/check_layers.py` — new `--prune-allowlist` flag
removes stale entries (allowlist entries чьи violations больше не в коде).

**Implementation:**
* `_prune_allowlist(keys)`: set difference `existing - current`.
* `_collect_all_violations()`: full repo scan (src/ + extensions/) для
  root-agnostic pruning (avoid false positives from `--root` scope).
* `stale` check в default scan использует `_collect_all_violations()`
  (was: current scan's keys only).

**Result:**
* Stale entries: 264 → 0 (31 pruned, остальные уже covered by extensions/
  scan или pre-existing legitimate).
* Allowlist size: 234 → 204 entries (-30, -13%).
* 3 NEW tests added (prune removes stale, no-op when no stale,
  collect_all covers both roots).

---

## S112 W2: Triage (commit `02c1e29f`)

**Output:** `reports/reaudit/s112_layer_triage.md`

Triage of 192+10=202 strict violations into 4 buckets:
* **A. Pre-S110 W2 legacy (~150):** Allowlist was rebuilt at S108 W2,
  dropping 200+ legacy entries. S110 W2 MERGE didn't recover (they were
  never re-added).
* **B. NEW after S110 W5 (13):** 3 core + 10 extensions. Actionable in W3.
* **C. Architectural exceptions (~30):** S110 W4 pattern (framework
  base classes). No new exceptions discovered.
* **D. Test/framework (~10):** S110 W1 pattern (`extensions/*/tests/`
  excluded). No new exclusions needed.

**Decision:** W3 = allowlist bulk-add for Bucket B (low risk).
AuditService move (Bucket B, 2 violations) deferred to S113+ (multi-day).

---

## S112 W3: Allowlist bulk-add (commit `22d890c3`)

**Result:** 3 NEW allowlist entries for Bucket B (3 core violations):

| Source | Import | Reason |
|---|---|---|
| `core/tenancy/sqlalchemy_filter.py` | `infrastructure.observability.correlation` | Tenant filter needs correlation_id для cross-tenant log tracing (same pattern as S109 W1 outbound_http.py → observability) |
| `core/audit/facade/__init__.py` | `services.audit.audit_service` | Legacy re-export from S103 W3 facade design (ADR-0190) |
| `core/audit/facade/_base.py` | `services.audit.audit_service` | Same as above (companion module) |

**Metric:**
* NEW violations: 3 → 0 (-3)
* Allowlist size: 204 → 207 entries (+3)
* Underlying --strict violations: 192+10=202 (unchanged)

---

## Post-S112 baseline (target)

| Metric | Pre-S112 | Post-S112 | Delta |
|---|---|---|---|
| Stale allowlist entries | 264 | 0 | -264 (-100%) |
| NEW core violations (default scan) | 3 | 0 | -3 (-100%) |
| NEW extensions violations (extensions scan) | 10 | 10* | 0 (already in allowlist from pre-S110 W2) |
| Allowlist size | 234 | 207 | -27 (-12%) |
| --strict underlying violations | 192+10=202 | 192+10=202 | 0 (unchanged) |

\* Discovered during W2 triage: 10 extensions violations are ALREADY
in the allowlist (pre-S110 W2 baseline, MERGE preserved). Default scan
correctly shows 0 NEW.

---

## Backlog after S112

* **S113+ multi-day:** AuditService move (core/audit/facade ← services/audit/audit_service)
* **S113+ multi-day:** Bucket A (150 pre-S110 W2 legacy) — re-allowlist
  or refactor (architectural decision)
* **Continuous:** --prune-allowlist в CI (auto-cleanup stale)
* **Continuous:** Bucket C (30 architectural exceptions) — already in
  EXTENSIONS_FRAMEWORK_EXCEPTIONS, no new entries needed

---

## References

* S111 W5 ADR-0197: https://docs/adr/0197-sprint-111-closure.md
* S112 W2 Triage: `reports/reaudit/s112_layer_triage.md`
* S110 W2 ADR: commit `3a3dc60d` (--update-allowlist MERGE fix)
* S110 W4 ADR: commit `af1e39f7` (EXTENSIONS_FRAMEWORK_EXCEPTIONS)
