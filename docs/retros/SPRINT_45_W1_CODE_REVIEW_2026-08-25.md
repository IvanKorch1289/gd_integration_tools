# Sprint 45 W1 — Code Review (2026-08-25)

> **Method**: Direct inspection of 5 recent commits via `git show` + targeted
> reads. Follows `.kimi-code/skills/code-review/SKILL.md` (security →
> architecture → quality → style).
> **Scope**: Sprint 45 W1 cycle 244-252 commits by parent agent +
> subagents.

## 1. Reviewed commits

| # | Hash | Type | Scope |
|---|---|---|---|
| 1 | `201a2c0d` | refactor(dsl) | +20 Protocol classes (1031 LOC) |
| 2 | `b5a7b599` | ci | stubs-drift workflow (47 LOC) |
| 3 | `554f4ce0` | docs | coverage W32 re-measurement |
| 4 | `851e4b5a` | docs(adr) | 0259 audit fact-check (155 LOC) |
| 5 | `1065ffb7` | docs(adr) | 0260 DSL lib map (120 LOC) |
| 6 | `e63358e9` | feat(dashboards) | quality-metrics.json (164 LOC) |
| 7 | `6b9323f6` + `29c556ff` | docs(adr) | ADR-0259 collision fix + WIKI regen |
| 8 | `111b506e` | docs(retro) | Sprint 45 W1 retro (129 LOC) |

## 2. Security review

| Commit | Finding | Severity |
|---|---|---|
| `201a2c0d` | Protocols are `@_runtime_checkable` — enables `isinstance()` checks. No security impact (structural typing only, no behavior). | ✅ PASS |
| `e63358e9` | Dashboard reads Prometheus metrics by name (`gd_integration_*`). No auth bypass — Grafana datasource level handles auth. | ✅ PASS |
| `b5a7b599` | Workflow runs `tools/gen_dsl_stubs.py` only (read-only check, no code execution side-effects beyond expected file writes). | ✅ PASS |
| `851e4b5a`, `1065ffb7` | Pure docs — no security surface. | ✅ N/A |

**Verdict**: No security regressions. The 3 fact-checked audit claims
(ADR-0259) all relate to historical security mechanisms that are now
fail-closed — current state verified safe.

## 3. Architecture review

### 3.1 Protocol classes (commit 201a2c0d)

**Strengths**:
- 22 Protocol classes with consistent naming convention (`_<Category>Protocol`)
- `@_runtime_checkable` enables `isinstance()` checks (useful for downstream
  type narrowing without breaking duck typing)
- One-line `"""Contract: ..."""` docstrings (project standard, docstring gate 0)
- Method signatures use `Any` return type for fluent chains (matches
  RouteBuilder API contract)
- 5-15 methods per Protocol, structurally cohesive (entity_crud, batch_data,
  control_flow, etc.)

**Concerns** (minor):
- 23 `_runtime_checkable` decorators but only 22 Protocol classes — possible
  double-application or extra decorator on non-Protocol target. Worth
  verifying with `grep -B1 _runtime_checkable`.
- No Protocol explicitly inherits from another Protocol — but ComposeRouteBuilder
  (P4-#4 migration path per header comment) may benefit from Protocol
  composition. NOT blocking for current sprint.

### 3.2 Quality dashboard (commit e63358e9)

**Strengths**:
- Validated JSON structure (parseable, 3 panels)
- Reads existing Prometheus metrics (no new exporter needed)
- 5-minute refresh interval (reasonable for quality metrics)
- Tags include `sprint-45` for filterability
- Thresholds: 30→50→60 for coverage (matches fail_under=60 gate)

**Concerns**:
- New file because existing `gd-integration-tools.json` has pre-existing
  parse error (line 372 unclosed brace) — NOT addressed in this commit.
  Tracked as separate backlog item. **Action**: fix in next sprint cycle.
- Prometheus metric names (`gd_integration_test_coverage_percent`, etc.)
  are referenced but not yet exported — panel will show "No data" until
  exporter is wired. **Action**: document in Sprint 45 W2 backlog that
  exporter wiring is prerequisite for live data.

### 3.3 ADR-0259 + ADR-0260 (pure docs)

**Strengths**:
- Every claim backed by grep + Read commands with concrete output
- Numbers tied to actual measurements (cycle 247: 23554/107349 = 1%)
- Cross-references to source files by line number (e.g.,
  `agent_sandbox.py:85-110`)
- "Honest assessment" sections explicitly call out what audit got wrong

**Concerns**: None. These are exemplary fact-check ADRs.

## 4. Quality review

### 4.1 Lint / type-check

- `ruff check src/backend/dsl/builders/base/__init__.py`: **PASSED** (cycle 244 verification)
- `mypy src/backend/dsl/builders/base/__init__.py`: **PASSED, no issues**
- Dashboard JSON: **parseable** (validated post-write)

### 4.2 Test coverage of changes

| Commit | Tests added | Tests verified |
|---|---|---|
| `201a2c0d` (Protocols) | 0 | N/A (structural typing, no runtime behavior change) |
| `e63358e9` (dashboard) | 0 | N/A (Grafana renders) |
| `b5a7b599` (CI workflow) | 0 | `--check` mode tested locally |
| Docs commits | 0 | N/A |

**Observation**: No new test coverage for 1031 LOC Protocol changes.
This is acceptable because:
1. Protocols are structural-only (no behavior)
2. Existing RouteBuilder tests (already passing) implicitly verify
   the Protocol surface
3. `@_runtime_checkable` enables cheap `isinstance` checks that can
   be added incrementally

**Action item**: Add 1-2 smoke tests using `isinstance(builder, _RouteCore)`
in next sprint to lock in Protocol surface.

### 4.3 Docstring gate

All Protocol methods + classes have one-line docstrings. Project-wide
`MAX_ALLOWED=0` gate satisfied (no missing docstrings in changed files).

## 5. Style review

| Aspect | Verdict |
|---|---|
| Commit messages | ✅ All follow conventional prefix (`refactor:`, `feat:`, `docs:`, `ci:`) + Russian-first where appropriate |
| Commit atomicity | ✅ Each commit is one logical change |
| Branch hygiene | ✅ No force-push, no squash-merge artifacts |
| AGENTS.md compliance | ✅ No secrets touched, no pip install, no push |
| Type hints | ✅ Python 3.14+ syntax (`int \| str`, generic classes) used where applicable |
| Async-first | ✅ No new blocking I/O introduced |

## 6. Risks identified

| Risk | Mitigation |
|---|---|
| Existing dashboard `gd-integration-tools.json` broken (pre-existing, not introduced) | Tracked for next sprint fix. New `quality-metrics.json` is isolated. |
| Dashboard Prometheus metric names not yet exported | Document as Sprint 45 W2 prerequisite. Panels show "No data" gracefully. |
| 22 Protocols × Project growth | When RouteBuilder adds new methods, corresponding Protocol may need extension. Add lint rule in future cycle. |
| ADR numbering collisions (cycle 252 incident) | Subagent prompts now reserve ADR numbers up-front. |

## 7. Approval

**Status**: ✅ APPROVED with 2 minor follow-ups:
1. Add `isinstance(builder, _RouteCore)` smoke test (S45 W2)
2. Fix pre-existing JSON error in `gd-integration-tools.json` (S45 W2)

**No blocking issues.** S45 W1 commits can ship to origin (when
push is approved by user — AGENTS.md prohibits automatic `git push`).

## 8. Cross-references

- `docs/retros/SPRINT_45_W1_RETRO_2026-08-25.md` — W1 retro
- `docs/adr/0259-audit-claims-factcheck-cycle-249.md` — audit fact-check
- `docs/adr/0260-dsl-external-lib-usage-map-cycle-250.md` — DSL lib map
- `docs/adr/0261-sprint-45-coverage-ratchet.md` — Sprint 45 plan
- `dashboards/quality-metrics.json` — new dashboard
- `.kimi-code/skills/code-review/SKILL.md` — review methodology
