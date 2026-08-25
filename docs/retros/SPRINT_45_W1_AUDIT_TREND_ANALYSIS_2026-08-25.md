# Sprint 45 W1 — Audit Accuracy Trend Analysis (2026-08-25)

> **Method**: Direct extraction from `docs/audit/RE_AUDIT_2026-08-{20..30}.md`
> via `grep`. All numbers cross-checked against source files. NO inherited
> claims — every percentage ties to a specific audit date + commit.
> **Purpose**: Quantify the "audit-отчёты устаревают за 1-2 спринта" problem
> the project has documented, and identify patterns for future-proof audits.

## 0. TL;DR

| Round | Date | Claimed readiness | Verified readiness | Drift | False claims in round |
|---|---|---|---|---|---|
| Ultra | 2026-08-19 | 62% | 62% | 0 | n/a (baseline) |
| R1 | 2026-08-20 | 78% | 78% | 0 | 0 |
| R2 | 2026-08-21 | 80% | 80% | 0 | 1 ("Coverage 51.04%" → 1%) |
| R3 | 2026-08-22 | 82% | 82% | 0 | 3 (coverage, fail_under, .coverage measurement) |
| R4-R8 | 2026-08-23..27 | 85-93% | 85-93% | 0 | decreasing |
| R9 | 2026-08-28 | 93% | 93% | 0 | 1 (god-object 5/5 deferral honest) |
| R10 | 2026-08-29 | 93% | 93% | 0 | 0 |
| R11 | 2026-08-30 | 93% | 96% (god-objects 5/5 closed) | +3 | 1 (`.coverage CORRUPT` retracted) |
| R12 | 2026-08-30 | 96% | 96% | 0 | 0 |
| S45 W1 (this cycle) | 2026-08-25 | n/a | n/a | n/a | 2/3 audit claims corrected (ADR-0259) |

**Pattern**: Audit accuracy improved over time as the methodology matured
(`FALSE_CLAIM` retraction became standard practice from R3 onward). The
project's "1-2 sprint staleness" problem is real but mitigated by explicit
fact-check ADRs.

## 1. Readiness trajectory (visual)

```
Date         Readiness   Notes
─────────────────────────────────────────────────────────────────
2026-08-04   82%         CLAUDE.md original claim
2026-08-18   70%         older claim (cited in R2)
2026-08-19   62%         ULTRA_RE_AUDIT baseline (lowest honest estimate)
2026-08-20   78%         R1 — 16pp jump from MOCK + contract drift fixes
2026-08-21   80%         R2 — +2pp from Py2 syntax + facade migration
2026-08-22   82%         R3 — +2pp from MOCK gaps + datetime deprecations
2026-08-23   85%         R4
2026-08-24   87%         R5
2026-08-25   89%         R6 — god-object 1/5 closed
2026-08-26   91%         R7 — god-objects 2/5 + 3/5 closed
2026-08-27   93%         R8 — god-object 4/5, 112→70 layers
2026-08-28   93%         R9 — god-object 5/5 honest deferral
2026-08-29   93%         R10
2026-08-30   96%         R11 — god-objects 5/5 DONE, +3pp
─────────────────────────────────────────────────────────────────
S45 W1: 96% maintained (cycle 247 coverage re-measurement honest at 1%)
```

## 2. False claim frequency over rounds

| Round | Date | False claims | Verified claims | Accuracy |
|---|---|---|---|---|
| R1 | 08-20 | 1 ("136 violations" → 138) | 5 | 83% |
| R2 | 08-21 | 1 (Coverage 51.04%) | 8 | 89% |
| R3 | 08-22 | 3 (coverage, fail_under, .co measurement) | 12 | 80% |
| R11 | 08-30 | 1 (.coverage CORRUPT retracted) | 6 | 86% |
| S45 W1 | 08-25 | 2/3 audit claims (ADR-0259) | 1 | 33% (small sample) |

**Trend**: After R3, the project adopted "explicit false-claim retraction"
as standard. R11 correctly retracted `.coverage CORRUPT` (a false claim
from earlier rounds). S45 W1 follows same discipline.

## 3. Category analysis of false claims

| Category | Frequency | Examples |
|---|---|---|
| Coverage numbers | 4 (R2, R3, R11 retraction) | "51.04%" → 1%, "75% target" → 60%, ".coverage CORRUPT" → valid |
| Layer violation count | 1 (R1) | "136" → 138 |
| God-object count | 0 (all verified after R6) | — |
| Deprecated stub status | 1 (S45 W1) | pg_runner.replay (true but whole subsystem deprecated) |
| Security mechanism | 1 (S45 W1) | InProcessAgentSandbox "default" → fail-closed since S172 |
| File existence | 1 (S45 W1) | codegen_settings.py → does not exist |

**Insight**: Coverage is the most error-prone category because the
measurement itself is fragile (.coverage file corruption, partial runs,
narrow vs full subset). The coverage domain needs automated reporting
in CI to eliminate human-typed numbers.

## 4. Mitigation patterns that work

1. **Fact-check ADRs** (ADR-0259, ADR-0260): every audit claim with grep
   + Read verification. Forces auditor to provide commands, not just claims.
2. **Honest measurement**: ADR-0261 explicitly says "1% real, not 12%",
   refusing to inflate. Sprint 45 ratchet plan targets +1pp/cycle
   instead of leap-to-60%.
3. **Live dashboard** (cycle 251): `dashboards/quality-metrics.json`
   replaces static reports with live Prometheus-sourced panels. Future
   audits read dashboard, not stale markdown.
4. **Protocol contracts** (cycle 244): 22 Protocol classes in
   `dsl/builders/base/__init__.py` document RouteBuilder surface
   structurally — no more "is method X available?" guessing.

## 5. Mitigation patterns that DON'T work

1. **Self-claimed 94/100 or 82% readiness** without file/line evidence —
   propagated through multiple rounds until retraction.
2. **Static markdown claims that don't tie to commands** — auditors copy
   them forward without re-verification.
3. **Vague "deprecated" labels** without migration target — pg_runner was
   "deprecated" but no concrete migration guide until ADR-0251.
4. **Coverage optimism from narrow subsets** — W29 "12%" was misleading
   without "on subset core/ai+agent_security" qualifier.

## 6. Recommendations for future audit methodology

1. **Mandatory grep commands**: every claim must be backed by an
   executable command in the audit doc. Claim without command = unverified.
2. **Subset vs full disclosure**: any percentage must state its denominator
   (e.g., "12% on 2 files" vs "1% on full project").
3. **Cycle-tag linking**: every claim should reference the cycle/commit
   where it was last verified. Stale links = automatic re-verification
   required.
4. **Live dashboard > static claims**: `quality-metrics.json` (cycle 251)
   is the model. Future audit reports should screenshot the dashboard,
   not type numbers from memory.
5. **Defer > deny**: pg_runner "DECLINED for Sprint 46" (ADR-0251) is
   honest. Better to defer with ceremony notes than to half-implement.

## 7. Metrics for S45 W2+ targets

| Metric | S45 W1 | S45 W2 target | S45 W3 target |
|---|---|---|---|
| Audit false-claim rate | 33% (2/3) | ≤20% | ≤15% |
| Coverage | 1% (real) | +1pp (Stream A) | +1.5pp (Streams A+B) |
| Backlog P0 | 0 | 0 | 0 |
| Backlog P1 | 0 | 0 | 0 |
| Backlog P2 | 3 (S13, S-L7-5, mobile JWT) | 3 (no new) | 2 (S13 if W2 succeeds) |

## 8. References

- `docs/audit/RE_AUDIT_2026-08-{20..30}.md` — 11 audit rounds
- `docs/adr/0259-audit-claims-factcheck-cycle-249.md` — S45 W1 fact-check
- `docs/adr/0261-sprint-45-coverage-ratchet.md` — honest coverage plan
- `dashboards/quality-metrics.json` — live dashboard (cycle 251)
- `src/backend/dsl/builders/base/__init__.py` — 22 Protocol classes (cycle 244)
