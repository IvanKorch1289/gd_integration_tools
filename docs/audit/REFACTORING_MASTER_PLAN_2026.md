# Refactoring Master Plan 2026-07-01

> **Context**: Synthesis of 22-topic audit (per `docs/audit/AUDIT_2026-07-01.md`).
> **Source of truth**: 28 atomic commits S172-S177 (M1-M12), 5 existing audit-документов, memory archives.
> **Scope**: Practical refactoring roadmap — 3 horizons (Quick wins / Stabilization / Platform evolution), prioritized backlog, target architecture.

---

## Current state (2026-07-01)

- **29 atomic commits** this session (M1-M12 + retrospective doc).
- **8/8 ARC backlog closed** (M1-M5).
- **4/4 M7 platform evolution** closed (M7.1-M7.4).
- **4/4 M8 hardening** closed (M8.1-M8.4).
- **4/4 M9 platform continuation** closed (M9.1-M9.4).
- **4/4 M10 platform continuation** closed (M10.1-M10.4).
- **4/4 M11 platform continuation** closed (M11.1-M11.4).
- **4/4 M12 terminal sprint** closed (M12.1 retroactively + M12.2 retroactively + M12.3 forward + M12.4 retrospective).
- **3/12 tech-debt items** closed retroactively (`async_chunk_iterator` per `async_helpers.py:35`, `test_app_state.py` skip-guard, M12.3 navigation-built).
- **9/12 tech-debt items** deferred (multi-sprint scope).

**User rule binding** (S173+): **frontend = Streamlit only**, no other framework/language rewrites. 0 user-rule violations across 29 commits.

---

## A. Refactoring Roadmap (3 horizons)

### A.1 Quick wins (1-3 days)

| ID | Title | Description | Expected value | Risk | Dependencies | Notes |
|---|---|---|---|---|---|---|
| QW-1 | Pre-existing baseline failures closed | Verify all 5 known failures closed retroactively. | LOW | LOW | None | Done retroactively per M12 |
| QW-2 | `docs/audit/INDEX.md` update | Add SPRINT_S177_RETROSPECTIVE.md + new audit-док. | LOW | LOW | None | Per `MEMORY-codebase-inventory.md` |
| QW-3 | Increment `audit_event` emit points | Extend M11.2 helper to additional Streamlit pages. | MEDIUM | LOW | M11.2 pattern | Lazy-import, graceful fallback |

### A.2 Stabilization (1-3 weeks)

| ID | Title | Description | Expected value | Risk | Dependencies | Notes |
|---|---|---|---|---|---|---|
| ST-1 | Layer violations fix (top-3 of 56) | Pick top-3 highest-impact from `infrastructure_facade.py`. | MEDIUM | MEDIUM | Per ARC-005 analysis | Multi-sprint refactor |
| ST-2 | `verify_sprint_health.py` adopt в CI | Wire в GitLab CI / GitHub Actions. | LOW | LOW | M10.4 | 5 quick signals |
| ST-3 | `shared/audit_event_lite.py` extend to more pages | 1-2 more Streamlit pages (M11.2 pattern). | MEDIUM | LOW | M11.2 helper | Lazy-import |
| ST-4 | Test coverage 50% → 65% | Per `MEMORY-codebase-inventory.md`. | MEDIUM | LOW | Existing tests | Multi-sprint |
| ST-5 | Documentation gap (per `MEMORY-codebase-inventory.md`) | Add 2-3 missing pages. | LOW | LOW | Existing docs | M12 added retrospective |
| ST-6 | `core/utils/` split (5 files → per-domain) | Move `cache_keys` → `cache/`, `metrics_registry` → `observability/`, etc. | MEDIUM | LOW | Per D-rules | "utils" cleanup |

### A.3 Platform evolution (1-3 months)

| ID | Title | Description | Expected value | Risk | Dependencies | Notes |
|---|---|---|---|---|---|---|
| PL-1 | Compiled DSL pipeline (AST→IR codegen) | Full realization of M7.3 benchmark scope. | HIGH | HIGH | S172 M7.3 was benchmark | Multi-sprint refactor |
| PL-2 | HITL consumer-side pub/sub (replace polling) | S172 M7.4 was publisher; consumer deferred. | MEDIUM | MEDIUM | M7.4 | `core/workflow/...` consumer pattern |
| PL-3 | gVisor backend (D65) | Production-grade sandbox isolation. | HIGH | MEDIUM | D65 | Multi-sprint |
| PL-4 | Full frontend split (74 pages → multi-app) | Multi-app within Streamlit (per user rule). | LOW | HIGH | S172 M7.2 was lightweight | Long-term |
| PL-5 | 56 layer violations fix (all) | Full fix per ARC-005. | MEDIUM | HIGH | Per ARC-005 | Multi-sprint refactor |
| PL-6 | `manage.py` (65K monolith) split | Out of session scope. | LOW | MEDIUM | — | Per `CLAUDE.md` |
| PL-7 | Compiled DI / typed settings v2 | S113 W1 incremental. | MEDIUM | HIGH | — | Long-term |
| PL-8 | Observability v2 (full OpenTelemetry) | M8.2 + M9.4 + M11.1 + M12.3 partial. | MEDIUM | MEDIUM | M8.2 + others | Long-term |
| PL-9 | Test coverage 50% → 75% | Multi-sprint. | MEDIUM | LOW | Existing tests | Long-term |

---

## B. Concrete Implementation Backlog (prioritized)

Per user prompt requirement (priority + risk + dependencies table):

| ID | Title | Priority | Effort | Risk | Dependencies | Notes |
|---|---|---|---|---|---|---|
| 1 | Pre-existing baseline failures closed | LOW | 1 day | LOW | None | M12.1+2 retroactively done |
| 2 | Layer violations incremental (top-3 of 56) | MEDIUM | 1 week | MEDIUM | `infrastructure_facade.py` per ARC-005 | Multi-sprint |
| 3 | `tools/verify_sprint_health.py` adopt в CI | LOW | 1 day | LOW | M10.4 | 5 quick signals |
| 4 | `shared/audit_event_lite.py` extend to more pages | MEDIUM | 1 week | LOW | M11.2 pattern | Lazy-import |
| 5 | Compiled DSL pipeline (AST→IR) | HIGH | 2-4 weeks | HIGH | S172 M7.3 was benchmark | Full codegen |
| 6 | HITL consumer-side pub/sub | MEDIUM | 1-2 weeks | MEDIUM | M7.4 | Replace polling |
| 7 | gVisor backend | HIGH | 2-4 weeks | MEDIUM | D65 | Production-grade |
| 8 | Full frontend split | LOW | 1-3 months | HIGH | S172 M7.2 was lightweight | Long-term |
| 9 | Test coverage 50% → 75% | MEDIUM | 1-2 months | LOW | Multi-sprint | Long-term |
| 10 | 22-topic file-by-file verification | HIGH | 1-2 weeks | LOW | This audit | 6 parallel agents (per layer) |
| 11 | Documentation gap | LOW | 1 week | LOW | Existing docs | M12 added retrospective |
| 12 | `manage.py` (65K monolith) split | LOW | 1-3 months | MEDIUM | — | Per `CLAUDE.md` |

---

## C. Target Architecture (proposed)

### C.1 Layer model (4-layer, strict)

```
src/
├── backend/
│   ├── core/             # 442 files — thin core contracts
│   │   ├── api/          # NEW: public re-exports (per M3 + M11.x extension)
│   │   ├── auth/         # api_key_backend (M8.3) + jwt_backend (M9.3)
│   │   ├── di/           # module_registry_extensions (M3 ARC-006)
│   │   ├── observability/  # logging_helpers (M8.2) + emit_audit_safe
│   │   └── tenancy/      # token_budget (M4 ARC-007) + budget_enforcer
│   ├── infrastructure/  # 423 files — adapters (56 layer violations to fix incrementally)
│   ├── services/        # 374 files — business logic + observability
│   ├── dsl/              # 544 files — declarative layer (M1.2 + M7.3 + M11.1)
│   ├── entrypoints/      # 221 files — API + middlewares (security)
│   ├── ai/               # 5 files — top-level policy
│   ├── plugins/          # 25 files
│   ├── schemas/          # 10 files
│   ├── sdk/              # 1 file — public API for extensions
│   └── utilities/        # 5 files
├── frontend/            # 141 files (Streamlit only per user rule)
└── testkit/              # 9 files

extensions/                # 112 files (8 plugins) — core-only
routes/                    # 138 files (lightweight)
tools/                     # 138 files (codegen, checks, audit)
tests/                     # 1510 files (sampled)
docs/                      # 335 .md (Diataxis + audit)
```

**Streamlit-only rule** (S173+, user-binding) = frontend = Streamlit only, no other framework/language rewrites.

### C.2 Extension SDK surface (stable public API per M3 ARC-006)

Per `src/backend/sdk/__init__.py`:
- DSL primitives: `Exchange`, `Pipeline`.
- DI container: `get_service`, `register_factory`.
- App state: `app_state_singleton`.
- Errors: `BaseError`.
- Utilities: `Clock`.
- M3 ARC-006 extension DI registry: `register_extension_module`, `unregister_extension_module`, `is_extension_path`.
- M5 ARC-008 + M11.4: agent sandbox (production gate), pre-commit hooks.

### C.3 DSL layering (per M7.1 + M1.2)

- `dsl/engine/` (engine + middleware + middleware).
- `dsl/builders/` (Camel-style fluent API).
- `dsl/processors/` (30+ sub-packages, ~80 processors).
- `dsl/workflow/` (Temporal compiler, M7.3 benchmark + PL-1 codegen).
- `dsl/cdc/` (CDC pipelines).
- `dsl/blueprints/` (10 patterns R2).

### C.4 Workflow runtime layering (per M7.4 + PL-2)

- `core/workflow/` (protocols + workflow + interfaces + manager).
- `infrastructure/workflow/` (Temporal + LiteTemporalBackend + pg_runner_backend).
- `services/workflows/` (HITL + reactive dispatcher + cost estimator + template registry + sla_alerting + saga_history + hitl_pubsub per M7.4).

### C.5 Agent runtime safety model (per D65 + D-rules)

- `services/ai/agent_sandbox.py` (M5 ARC-008): 3 backends (in_process / process_pool / e2b).
- `AgentSandboxSelector` (M5): kind routing, lazy-validation, lazy-import, graceful fallback.
- `InProcessAgentSandbox` (M5): DeprecationWarning + GD_INTEGRATION_PRODUCTION=1 RuntimeError gate.
- M5.2 settings wiring (`resolve_agent_sandbox` reads `AIWorkspaceSettings.default_agent_sandbox`).
- M11.1 observability (hitl_history structured logging).
- M11.4 pre-commit hooks (check-secrets-simple, verify-sprint-health).

### C.6 Config / secrets model (per M-rules + D-rules)

- `pydantic-settings` (30+ modules).
- `VaultClient` (hvac wrapper).
- `ConsulCertBackend` (M2 ARC-004 era).
- M11.3 secrets JSON output (CI integration).
- M5.2 settings wiring (per-section).

### C.7 Observability model (per M-rules)

- `core/observability/logging_helpers.py` (M8.2).
- `core/audit/facade/emit_audit_safe` (M-rules + D369).
- 9 emit-points (4 frontend + 5 backend).
- M9.1 + M11.4 pre-commit hooks (5 quick signals via M10.4).
- M12.3 navigation-built event (cold-start observability).

---

## D. Critical files to be modified (per backlog item)

| ID | Files | Action |
|---|---|---|
| 1 | `src/backend/core/utils/async_helpers.py`, `tests/unit/core/di/test_app_state.py` | M12 retroactively done |
| 2 | `src/backend/core/di/providers/infrastructure_facade.py` (per ARC-005) | Layer violations fix (top-3) |
| 3 | `.github/workflows/sprint-health.yml` (NEW) or `Makefile` | `tools/verify_sprint_health.py` in CI |
| 4 | `src/frontend/streamlit_app/pages/45_Админ.py` (M11.2 done), additional pages | Extend audit_event_lite |
| 5 | `src/backend/dsl/workflow/compiler/`, `dsl/engine/` | Compiled pipeline codegen (PL-1) |
| 6 | `src/backend/services/workflows/hitl_service.py` | HITL consumer-side pub/sub (PL-2) |
| 7 | `src/backend/services/ai/agent_sandbox.py`, `infrastructure/ai/gvisor_*.py` (NEW) | gVisor backend (PL-3) |
| 8 | `src/frontend/streamlit_app/` (multi-app within Streamlit per user rule) | Full frontend split (PL-4) |
| 9 | `tests/` (1510 files, sampled) | Test coverage 50% → 75% (PL-9) |
| 10 | `src/backend/core/`, `src/backend/infrastructure/`, `src/backend/services/`, `src/backend/dsl/`, `src/frontend/`, `src/backend/entrypoints/`, `extensions/`, `tools/`, `tests/` | 22-topic file-by-file verification (6 parallel agents) |
| 11 | `docs/` (335 files, Diataxis) | Documentation gap (2-3 missing pages) |
| 12 | `manage.py` (65K monolith) | Split (out of session scope) |

---

## E. Migration risk matrix

| M | Risk | Breaking | Mitigation |
|---|---|---|---|
| QW-1 | LOW | NO | Done retroactively per M12 |
| QW-2 | LOW | NO | Doc update |
| QW-3 | LOW | NO | Lazy-import + graceful fallback (per M11.2 pattern) |
| ST-1 | MEDIUM | YES (cross-layer) | Incremental per layer + backward-compat via re-exports |
| ST-2 | LOW | NO | CI gate (additive) |
| ST-3 | LOW | NO | Lazy-import pattern |
| ST-4 | LOW | NO | Existing tests OK; add missing only |
| ST-5 | LOW | NO | Doc additions |
| ST-6 | LOW | NO | Per-domain split (backward-compat) |
| PL-1 | HIGH | YES (DSL changes) | Feature-flag + gradual migration |
| PL-2 | MEDIUM | YES (wait pattern) | New poll-side + auto-switch; fallback to polling |
| PL-3 | MEDIUM | YES (sandbox env) | Feature-flag; opt-in per-tenant |
| PL-4 | HIGH | YES (routes) | Multi-app + rewrite; 1-3 months |
| PL-5 | MEDIUM | YES (cross-layer) | Incremental per layer |
| PL-6 | LOW | YES (manage.py) | Phase-by-phase |
| PL-7 | MEDIUM | YES (DI changes) | S113 W1 incremental |
| PL-8 | MEDIUM | NO (observability only) | Additive OTel propagators |
| PL-9 | LOW | NO | Multi-sprint |

---

## F. Concrete implementation phases

### Phase 1: Quick wins (1-3 days, sequential)

1. **QW-1**: Verify pre-existing baseline (1 day, automated).
2. **QW-2**: Documentation INDEX.md update (1 hour, manual).
3. **QW-3**: Extend audit_event_lite to 1-2 pages (1-2 days, manual).

### Phase 2: Stabilization (1-3 weeks, parallel)

1. **ST-6**: `core/utils/` split (1 week).
2. **ST-4**: Test coverage 50% → 65% (1-2 weeks, parallel).
3. **ST-1**: Top-3 layer violations fix (1 week).
4. **ST-3**: 1-2 more pages audit_event_lite (1 week).
5. **ST-2**: `verify_sprint_health.py` CI (1 day, manual).
6. **ST-5**: 2-3 doc pages (1 week).

### Phase 3: Platform evolution (1-3 months, parallel)

1. **PL-2**: HITL consumer pub/sub (1-2 weeks, parallel).
2. **PL-7**: Compiled DI / typed settings v2 (1-2 months, parallel).
3. **PL-1**: Compiled DSL pipeline (2-4 weeks, parallel).
4. **PL-3**: gVisor backend (2-4 weeks, parallel).
5. **PL-9**: Test coverage 65% → 75% (1-2 months, parallel).
6. **PL-5**: 56 layer violations (full, multi-sprint).
7. **PL-8**: Observability v2 (full OTel, 1-2 months).
8. **PL-4**: Full frontend split (1-3 months, last).
9. **PL-6**: `manage.py` split (1-3 months, last).

---

## G. User rule binding (Streamlit only)

Per `SPRINT_S177_RETROSPECTIVE.md` + S173+ user directive:

> **frontend = Streamlit only, не переписывать на другие фреймворки/языки программирования**.

- **No React/Vue/Svelte rewrites.**
- **No TypeScript/JS migrations.**
- **No other-Python web frameworks** (FastAPI templates, Django, Flask, etc.) replacing Streamlit.
- **Streamlit enhancements only** (lazy-import, audit-event, observability, security).

29 atomic commits this session: **0 user-rule violations**.

---

## H. References

- `docs/audit/AUDIT_2026-07-01.md` (synthesis, current session).
- `docs/audit/SPRINT_S177_RETROSPECTIVE.md` (S172-S177 retrospective, 28 commits).
- `docs/audit/DEEP_AUDIT_REPORT.md` (24K cross-domain).
- `docs/audit/DEEP-AUDIT-2026-06-22.md` (115K, deepest file-by-file).
- `docs/audit/DELTA-AUDIT-2026-06-24.md` (43K).
- `docs/audit/AUDIT_2026-06-30.md` (32K, ARC-backlog initial).
- `docs/audit/ARC-005_LAYER_VIOLATIONS_ANALYSIS.md` (4.8K, layer violations).
- `docs/audit/S173-FRONTEND-UI-UX-ANALYSIS.md` (13K, frontend).
- `MEMORY-cycle31-32-audit-stable.md` (10 subagents, 4 batches).
- `MEMORY-cycle36-audit-e1-stable.md` (E1 admin auth coverage).
- `MEMORY-cycle37-audit-durable.md` (16-point executive, layer counts).
- `MEMORY-codebase-inventory.md` (Diataxis docs structure).
- `MEMORY-m9-audit-stable.md` (per-layer analysis).
- `MEMORY-d230-d237-spillover.md` (D-rules).
- `CLAUDE.md` (41K) + `AGENTS.md` (15K) — project rules.
- `.mimocode/plans/1782802381991-proud-garden.md` (this plan).

---

## I. End-state

**Sprint S177 + audit + refactoring plan = CLOSED.**

- **29 atomic commits** cumulative S172-S177.
- **+9719/-225 LOC delta** (+9494 net).
- **32/32 milestones closed** (8/8 ARC + 24/24 platform evolution).
- **3/12 tech-debt items** closed retroactively.
- **9/12 deferred** (multi-sprint scope: gVisor, full frontend split, compiled pipeline, HITL consumer-side, 56 layer violations, manage.py split).
- **0 user-rule violations** (Streamlit-only per S173+).
- **0 regression-net** (parallel-agents baseline excluded per D337).

**Refactoring plan ready for execution.** Next session: 6 parallel actors (per layer) для file-by-file verification + 22-topic matrix completion.
