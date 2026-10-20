# Per-SHA evidence bundle — `35bf69eae` (2026-10-19)

Evidence bundle для HEAD `35bf69eae31451f252657a8cb0673f00035424e6`,
созданный для закрытия **G-14** (per-SHA evidence gap) из
`deliverables/prod-readiness-review-2026-10-19/REVIEW.md` §2 row G-14.

## Layout

| File | Purpose |
|---|---|
| `SHA.txt` | short/full SHA + recent commit context |
| `SUMMARY.md` | narrative snapshot: gates, drift findings, verdict drift |
| `git_log_10.txt` | raw `git log -10` на момент bundle creation |
| `startup_time_gate.txt` | raw output of `python tools/checks/startup_time.py` (re-measurement) |
| `auth_inventory_test.txt` | raw pytest output of `test_per_op_auth_inventory.py` |

## Key findings this bundle records

1. **G-14 closed** — direct evidence для `_closing_` review's
   per-SHA evidence gap.

2. **G-10 re-verified** — startup-time gate measured at 2.452s median
   (within 3.120s regression limit). **Drift finding**: REVIEW §12 recorded
   1.472s on same SHA; my measurement 2.452s = +66%. Reconciliation needed
   in next REVIEW update (likely cause: outdated 2.145s budget reference
   predates baseline ratchet 2026-10-14 which set baseline 2.40s).

3. **G-9 independently re-verified** — `pytest tests/integration/security/
   test_per_op_auth_inventory.py` → 458 passed / 0 failed / 11.08s.
   Full coverage of 458 non-public routes (admin/auto/CRUD/SOAP/SSE/CDC/
   webhooks/express).

## Related

- `deliverables/prod-readiness-review-2026-10-19/REVIEW.md` §2 G-14 row + §10 OQ-4 + §12
- `deliverables/prod-readiness-review-2026-10-19/evidence/whole_tree_e59534f88_then_report.md`
  (whole-tree pytest run; OQ-6 evidence from prior round)
- `.baselines/startup-time.json` (baseline ratchet source for §2a)
