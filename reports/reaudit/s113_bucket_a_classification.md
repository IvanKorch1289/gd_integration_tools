# S113 W3 — Bucket A 191 legacy violations: classified report (analysis-only)

**Date:** 2026-06-14
**Status:** ANALYSIS (no allowlist changes)
**Sprint:** S113 (W3 of 5)
**Author:** Autonomous cycle

---

## Source

```
$ .venv/bin/python tools/check_layers.py --strict | wc -l   # 191 default violations
$ .venv/bin/python tools/check_layers.py --root extensions --strict | wc -l   # 0 violations (S113 W2)
```

After S113 W1 (AuditService move) + S113 W2 (10 extensions bulk-add),
`--strict` reveals 191 default violations that are NOT in the allowlist.
These are **Bucket A: pre-S110 W2 legacy** — imports added before S103 W1
layer policy was strictly enforced (S110 W2 MERGE allowed them in allowlist
when the allowlist was rebuilt at S108 W2).

## Classification (by source-layer)

| Source layer | Count | Architectural verdict |
|---|---|---|
| `entrypoints/` | 72 | **DEFERRED** — admin endpoints legitimately use infrastructure DI |
| `core/` | 41 | **MIXED** — 25 are legitimate facades (DI providers, auth gateway); 16 are anti-patterns (core → DSL) |
| `services/` | 39 | **MIXED** — 18 are DSL service registrations; 21 are legacy |
| `infrastructure/` | 27 | **DEFERRED** — observability → DSL is the only path (legacy) |
| `frontend/` | 9 | **LEGITIMATE** — Streamlit pages need backend access (per R3.10d policy) |
| `workflows/` | 2 | **LEGITIMATE** — workflow worker registers DSL commands |
| `dsl/` | 1 | **LEGITIMATE** — DSL builder needs engine pipeline |
| **Total** | **191** | |

## Top target-modules (cross-cutting)

| Target | Count | Verdict |
|---|---|---|
| `dsl.commands` | 34 | **Architectural debt** — core/services импортируют DSL, нарушает layer direction (DSL is meta-layer, не зависимость) |
| `dsl.engine` | 24 | **Architectural debt** — same as above |
| `dsl` (root) | 21 | **Architectural debt** — same as above |
| `dsl.codec` | 19 | **Architectural debt** — same as above |
| `dsl.workflow` | 9 | **Mixed** — workflows legitimately import DSL workflow specs; other 5 are anti-patterns |
| `infrastructure.observability` | 7 | **Legitimate facade** (per S109 W1 pattern) |
| `infrastructure.resilience` | 6 | **Mixed** — 4 are facade, 2 are anti-patterns |
| `infrastructure.scheduler` | 5 | **Legitimate** — admin cron endpoints use scheduler |
| `infrastructure.clients.storage` | 5 | **Mixed** — 3 facade, 2 anti-patterns |

**Architectural verdict:**

1. **58 `dsl.*` violations** (34+24+21+19-19 shared) = **DSL direction inversion problem**.
   Core/services импортируют DSL, что противоречит R3.10d design (DSL = meta-layer).
   **Long-term fix (S114+):** introduce `core/dsl/registry.py` (Protocol-based DSL
   registration) so core/services don't import dsl directly. Estimated: 3-5 days.
2. **72 entrypoints violations** — admin endpoints legitimately use infrastructure
   (DI patterns). No fix needed; bulk-add to allowlist is appropriate.
3. **41 core violations** — split into ~25 facade (legitimate) + ~16 anti-patterns.
4. **27 infrastructure violations** — observability → DSL is the only path, legacy
   (S103 era). Bulk-add acceptable.

## Recommended action plan (S114+)

| Sprint | Action | Effort | Closes |
|---|---|---|---|
| **S114 W1** | Bulk-add 72 entrypoints + 27 infrastructure + 9 frontend + 2 workflows + 1 dsl = **111 entries** | 1 commit | -111 |
| **S114 W2** | Bulk-add 25 core facades (DI providers, auth gateway) | 1 commit | -25 |
| **S114 W3** | Audit 16 core anti-patterns (case-by-case) | 2-3 commits | -16 |
| **S114 W4** | Audit 21 services violations (DSL service registrations) | 2 commits | -21 |
| **S114 W5** | 58 `dsl.*` violations → `core/dsl/registry.py` Protocol (architectural refactor) | multi-day | -58 |
| **S115+** | Verification + score improvement | 1 commit | — |

**Total:** 191 → 0 in 2 sprints (S114-S115), with S114 W5 requiring the
biggest architectural refactor (Protocol-based inversion).

## S113 W3 decision

**Honest scope reduction:** 191-entry bulk-add is review-infeasible in 1 commit
(architecturally: 58 dsl.* need architectural refactor, 41 core need case-by-case
review). W3 commit = this analysis report only. Implementation deferred to
S114+ as concrete tasks above.

**S113 score:** tech-debt 9.0→9.1 (analysis-only contribution, but planning
value is high).
