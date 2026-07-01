# Audit Methodology (S178 sprint-1 + multi-session continuation)

> **Дата**: 2026-07-01 (per S178 sprint-1 + refactoring master plan ST-5).
> **Версия**: 1.0.
> **Назначение**: описывает методологию continuation audit (для multi-session agent dispatch) — backlog item #10 из `docs/audit/REFACTORING_MASTER_PLAN_2026.md`.
> **Связь**: continuation of `docs/audit/AUDIT_2026-07-01.md` (synthesis, 22-topic) + `docs/audit/REFACTORING_MASTER_PLAN_2026.md` (3-horizon roadmap) + `docs/audit/SPRINT_S177_RETROSPECTIVE.md` (32-commit history) + `docs/audit/INDEX.md` (navigation hub).

---

## TL;DR

Эта doc описывает **how to extend audit** в multi-session формате (6 parallel agents по layer), как требует backlog #10. Каждый agent делает file-by-file scan в своей layer + 22-topic checklist output. Synthesis session комбинирует agent outputs → final 22-topic report.

---

## A. Multi-session pattern (per D387 synthesis-by-meta-plan pattern)

### A.1 Per-session structure (current)

Per `docs/audit/AUDIT_2026-07-01.md` Section Caveats + `MEMORY-cycle37-audit-durable.md`:

1. **Session 1 (synthesis, closed 2026-07-01)**: meta-plan + A-M synthesis based on existing audit-документы + memory archives + 28 my atomic commits. NOT file-by-file (5041 source files = 17 days at per-file level).
2. **Session 2 (file-by-file, deferred to next sessions)**: 6 parallel agents по layer (core 442 / infrastructure 423 / services 374 / dsl 544 / entrypoints+frontend 362 / extensions+tools 388). Каждый agent делает file-by-file scan + 22-topic checklist output.
3. **Session 3 (synthesis-2, deferred)**: combine agent outputs → final 22-topic report (replaces/extends current `AUDIT_2026-07-01.md`).
4. **Session 4+ (refactoring execution)**: 3-horizon roadmap (QW/ST/PL) per master plan.

### A.2 Memory state carry-over (per `notes.md` last turn)

- `~/.local/share/mimocode/memory/sessions/ses_0e8b28359ffee9pSUdEJL54JYL/notes.md` — 36 atomic commits cumulative.
- `docs/audit/AUDIT_2026-07-01.md` (30K) — master audit synthesis (sections A-M).
- `docs/audit/REFACTORING_MASTER_PLAN_2026.md` (12K) — 3-horizon roadmap + 12-item backlog.
- `docs/audit/INDEX.md` (QW-2 closed) — navigation hub.

---

## B. Per-layer agent dispatch (backlog #10)

### B.1 Layer breakdown (5041 files, 14878 dirs)

| Layer | File count | Domain | Notes |
|---|---|---|---|
| `src/backend/core/` | ~442 | protocols + DI + auth + observability | D-rules + capability model (V11.1) |
| `src/backend/infrastructure/` | ~423 | DB + cache + messaging + observability | 56 layer violations (canonical) |
| `src/backend/services/` | ~374 | business + AI + workflows | M-rules + extension DI |
| `src/backend/dsl/` | ~544 | engine + workflow + builders + blueprints | EIP patterns + 80 processors |
| `src/backend/entrypoints/` + `src/frontend/` | 221 + 141 = 362 | API + middlewares + Streamlit frontend | User rule: Streamlit only |
| `extensions/` + `routes/` + `tools/` + `tests/` | 112 + 138 + 138 + 1510 = 1898 | extensions + tests + DX | D345 ADR pending |

### B.2 Per-agent 22-topic checklist output (template)

Каждый agent отчитывается по 22 секциям (per `AUDIT_2026-07-01.md` Section E):

1. JupyterHub / notebooks
2. Layer independence
3. Performance
4. Custom agent policies
5. Global DI
6. Duplicate libraries
7. Dead / smelly code
8. Directory organization
9. Import ergonomics
10. Scheduler / triggers
11. Agent workflow
12. Frontend
13. Documentation
14. DSL directory scanning
15. CDC and DSL
16. Multi-protocol
17. DSL transform / aggregate
18. Middleware and DSL
19. External DBs
20. Configuration / secrets
21. RPA / SSH / files
22. Caching / SSE

For each section:
- **Status**: FOUND / PARTIAL / NOT FOUND / UNSAFE / CRITICAL.
- **Evidence**: file paths + line refs.
- **Problems**: smells, risks, duplications, dead code.
- **Recommendations**: keep / refactor / replace with library / remove / move to extension SDK / wrap in DSL.
- **Priority**: HIGH / MED / LOW.
- **Migration risk**: LOW / MED / HIGH.

### B.3 Agent dispatch pattern (per D-rules)

Per D-rules (D235, D387, D388):
- 6 parallel agents (one per layer).
- Each agent: read-only file-by-file scan + 22-topic checklist output.
- Synthesis session: combine agent outputs → final A-M report.
- All findings (D-rules, fixes, recommendations) per agent — но в D-rules-compatible format.

### B.4 Synthesis pattern (per D387 + D388)

Per A-M framework (D389):
- A. Executive summary (10 findings).
- B. File inventory (layer-aggregated counts).
- C. Domain summaries (per layer).
- D. Layer & dependency matrix (4-layer + violations).
- E. 22-topic matrix (FOUND/PARTIAL/NOT FOUND/UNSAFE).
- F. DSL coverage map (30+ sub-packages, ~80 processors).
- G. Duplicate / smell / dead code.
- H. Dependencies review.
- I. Documentation review.
- J. Refactoring roadmap (3 horizons: QW/ST/PL).
- K. Target architecture.
- L. Prioritized backlog.
- M. Final verdict.

---

## C. Continued audit pattern (post-sprint-1)

### C.1 Per-milestone lightweight scope (per M6 precedent)

- 1-2 file scope per milestone.
- Honest scope (per M6): regression-fix + analysis-doc, not fix-all-58.
- 3-perspective review per milestone (Security/Architecture/Ops).
- Atomic commit per milestone with conventional prefix.

### C.2 D-rules binding (per MEMORY + AGENTS.md)

- **D121** = no `git stash`/`reset`/`clean` (parallel-agents compatibility).
- **D248** = NEVER read `.env*`, `secrets/**`, `*.pem`, `*.key`.
- **D328** = re-read file via `read` before `edit` tool.
- **D337** = `@pytest.mark.pre_existing` for known-failing baseline.
- **D345** = extension-shadowing ADR (deferred).
- **D387** = synthesis-by-meta-plan pattern (large-repo audit).
- **D388-D393** = audit synthesis content shape (cycle 38 S177 audit-exec).

### C.3 User rule binding (S173+)

- **frontend = Streamlit only**, не переписывать на другие фреймворки/языки программирования.
- **Russian-language mode** (S177+).

---

## D. Pre-existing baselines + known issues (per D337)

### D.1 Pre-existing baseline (5 known failures, marked `@pytest.mark.pre_existing`)

- `tests/unit/core/ai/test_pydantic_ai_client_exceptions.py::test_top_level_gateway_imports`
- `tests/unit/core/ai/test_workspace_cleaner.py::test_stop_before_start_is_safe`
- `tests/unit/services/ai/test_pydantic_ai_provider.py::TestPydanticAIProvider::test_instantiates`
- `tests/unit/services/ai/test_pydantic_ai_provider.py::TestPydanticAIProvider::test_adapter_importable`
- `tests/unit/core/ai/test_gateway_pipeline_mixin.py::test_resolve_policy_none_in_soft_mode_returns_none` (F821 in 16_Воркфлоу.py:160)

### D.2 56 layer violations в `infrastructure_facade.py` (canonical S22 W3)

Per ARC-005 analysis: deliberate design pattern. **NOT fix per single milestone.** Multi-sprint refactor (PL-5 backlog item).

---

## E. References

- `docs/audit/AUDIT_2026-07-01.md` — master audit synthesis.
- `docs/audit/REFACTORING_MASTER_PLAN_2026.md` — 3-horizon roadmap + 12-item backlog.
- `docs/audit/SPRINT_S177_RETROSPECTIVE.md` — 32-commit history.
- `docs/audit/INDEX.md` — navigation hub (QW-2 closed).
- `docs/audit/ARC-005_LAYER_VIOLATIONS_ANALYSIS.md` — 56 violations analysis.
- `docs/architecture/memory_structure.md` (QW-1) — memory + session-recovery rules.
- `.mimocode/plans/1782802381991-proud-garden.md` — meta-plan.
- `MEMORY-cycle37-audit-durable.md` — 16-point executive + layer counts.
- `MEMORY-d230-d237-spillover.md` — D-rules (D235 agent orchestration, D387 synthesis pattern).
- `CLAUDE.md` (41K) + `AGENTS.md` (15K) — project rules.

---

## F. End-state (this doc, QW-3.5)

This document `docs/audit/AUDIT_METHODOLOGY.md` (S178 ST-5 deliverable) provides:
- Section A: Multi-session pattern (current session-closed + future per-layer agent dispatch).
- Section B: Per-layer breakdown + per-agent 22-topic checklist template.
- Section C: Continued audit pattern (per-milestone + D-rules + user rules).
- Section D: Pre-existing baselines + 56 layer violations.
- Section E: References.
- Section F: End-state.

**ST-5 closed retroactively** (1/12 backlog items closed this turn).
**Next backlog item**: continuation of audit-mode via file-by-file agent dispatch (per backlog #10) — multi-session effort.
