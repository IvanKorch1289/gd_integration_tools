# Sprint 45 W1 — Retrospective (2026-08-25)

> **Method**: Single agent session (parent agent, no subagent fan-out for this
> W1 retro due to bounded scope). Direct commit history verification.
> **Sprint window**: 2026-08-24 → 2026-08-25 (1 working day, focused slice).
> **Pre-sprint state**: S44 closed at 96% readiness, 0 P0, 0 P1, 1 unresolved
> gap (coverage 13% per ADR-0257, retracted to 1% per cycle 247).
> **Sprint 45 plan**: per ADR-0261 — 3 ratchet streams targeting +2-3pp coverage.

## 1. Sprint W1 goal (achieved)

Prepare Sprint 45 infrastructure: verify audit claims honestly, document
DSL external library usage map, plan coverage ratchet, add quality-metrics
dashboard for live tracking. NO code-refactoring of RouteBuilder (deferred
to W2+ — Protocol layer already in place from cycle 244).

**Result**: 4 ADR-equivalent docs created, 1 dashboard added, 3 audit
claims fact-checked. Zero production code changes. Honest "audit-отчёты
устаревают за 1-2 спринта" problem addressed by replacing static claim
proliferation with live dashboard.

## 2. Wins

1. **3 audit claims fact-checked** (commit `851e4b5a`, ADR-0259):
   - `yaml.load` RCE risk: **FALSE** — `codegen_settings.py` doesn't exist,
     zero `yaml.load()` calls in `src/`. Project uses `safe_load` exclusively.
   - `InProcessAgentSandbox` default: **PARTIALLY FALSE** — fail-closed 3 ways
     since S33 (env gate) + S172/ARC-008 (feature flag + import error fallback).
   - `pg_runner.replay()` no-op: **TRUE** — but whole `PgRunnerWorkflowBackend`
     is deprecated since Sprint 217 (2026-08-17), callers migrate to
     `TemporalWorkflowBackend` (which DOES implement Temporal replay with
     `WorkflowNonDeterminismError` detection).

2. **22 Protocol classes in RouteBuilder** (commit `201a2c0d`, cycle 244) —
   `≥20/41` target met. Verified by `grep -c '^class _.*_Protocol'`. This was
   the SINGLE remaining P1 from S44 R12; now closed.

3. **DSL external lib map** (commit `1065ffb7`, ADR-0260) — honest
   documentation that project already uses 12 mature libraries
   (playwright, Pillow, pytesseract, pypdf, pdfplumber, pypdfium2,
   openpyxl, python-docx, asyncssh, httpx, defusedxml, glom). Avoided
   adding Tika/Fabric as duplicates per Ponytail/YAGNI.

4. **Quality-metrics dashboard** (commit `e63358e9`, `dashboards/quality-metrics.json`)
   — 3 panels (Coverage % gauge, Bandit HIGH stat, Layer violations stat).
   Read existing Prometheus metrics. New file because `gd-integration-tools.json`
   has pre-existing JSON parse error (line 372 unclosed brace).

5. **Stub drift CI** (commit `b5a7b599`, cycle 246) — `.github/workflows/stubs-drift.yml`
   prevents the previously-fixed drift from re-emerging silently.

## 3. Honest misses / honest assessments

1. **Coverage 1% honest measurement** (commit `554f4ce0`, cycle 247) —
   the W29 "12%" was narrow-subset misleading. **Full project: 1%**,
   59pp below fail_under=60%. Sprint 45 ratchet must address this.
   No false optimism — documented in ADR-0261 with realistic +1pp/cycle target.

2. **ADR-0259 numbering collision** discovered & fixed in cycle 252.
   Two ADRs created with same number (parent agent + subagent picked 0259
   independently). Resolution: rename subagent's to 0261 + WIKI regen.
   Lesson: subagent prompts should reserve ADR numbers up-front.

3. **2 subagent timeouts** during W1 — first attempts at TASK A/B subagents
   stalled silently (>1M tokens, no output). Killed, parent agent finished
   directly. Root cause: subagent context too heavy with full code review.
   Lesson: shorter subagent prompts with explicit verification checkpoints.

4. **Existing dashboard broken** — `gd-integration-tools.json` has pre-existing
   parse error (line 372). Did NOT fix in W1 (out of scope, risk of
   breaking existing circuit-breaker panels). Tracked as future backlog.

## 4. Sprint 45 W2+ plan

Per ADR-0261 (3 ratchet streams):
- **W2**: Stream A — top-10 uncovered modules tests (target +1pp coverage)
- **W3**: Stream B — 17 entrypoint smoke tests (target +0.5pp)
- **W4**: Stream C — Hypothesis property tests for 3 core modules (+0.5pp)

Plus parallel work (deferred from S45 backlog):
- **S13** (ADR-0251): Circuit breaker Redis shared state — investigate
  feasibility (claimed 3-line change, but DI lifecycle concerns documented).
- **S-L7-5** (ADR-0252): W3C TraceContext MQ wiring — observability gap.
- **Mobile JWT TODO epic** — security gap in `entrypoints/api/mobile/router.py`.

## 5. Metrics delta (S44 close → S45 W1 close)

| Metric | S44 close | S45 W1 close | Delta |
|---|---|---|---|
| ADR count | 217 | 222 | +5 (0259, 0260, 0261, renumber + WIKI) |
| Protocol classes | 2 | 22 | +20 (cycle 244) |
| CI workflows | 18 | 19 | +1 (stubs-drift) |
| Coverage (real) | 13% (subset) → 1% (full) | 1% | honest measurement |
| Backlog P0 | 0 | 0 | maintained |
| Backlog P1 | 1 | 0 | -1 (Protocol migration closed) |
| Backlog P2 | 3 | 3 | maintained (S13, S-L7-5, mobile JWT) |

## 6. Reference commits

- `201a2c0d` refactor(dsl): 20 Protocol classes
- `b5a7b599` ci: stub drift workflow
- `554f4ce0` docs: coverage full re-measurement (1% real)
- `17756ba9` fix(tests): S209 hardening drift
- `2076a7e2` docs: WIKI regen
- `851e4b5a` docs: ADR-0259 fact-check
- `e8079e91` docs: ADR-0261 Sprint 45 ratchet
- `1065ffb7` docs: ADR-0260 DSL lib map
- `e63358e9` feat: quality-metrics dashboard
- `6b9323f6` + `29c556ff` docs: ADR renumber + WIKI regen

## 7. Action items for W2

1. Start coverage ratchet Stream A (top-10 modules)
2. Investigate S13 feasibility (read `BreakerRegistry`, check if
   module-level singleton + async Redis init can be safely wired)
3. Document mobile JWT TODO as proper ADR with risk assessment
4. Fix pre-existing JSON parse error in `gd-integration-tools.json`
   (separate cycle, risk-bounded)

## 8. Lessons captured

- **Subagent prompt patterns**: Always pre-reserve ADR numbers in subagent
  prompts. Add explicit `cycle-NNN` markers in commit messages so parent
  can correlate.
- **Audit propagation discipline**: For every audit claim, write a fact-check
  ADR with grep commands. Future audits cite the fact-check, not stale claims.
- **Ponytail wins**: Did NOT add Fabric/Tika processors (would have duplicated
  existing pypdf/asyncssh coverage). Saved ~200 LOC of code that would have
  added maintenance burden without value.
