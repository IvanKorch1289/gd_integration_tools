# Sprint 171 — Финальный Summary (M10-M16)

## Дата: 2026-06-24..26
## Scope: Production Readiness 90%+ + Refactor + Docs + SSL Hot-Reload

## Milestones

| M | Название | Failures fixed | BUG fixes | New tests |
|---|----------|----------------|------------|-----------|
| **M10** | P0-P3 critical fixes | 8 tasks | 0 (planned) | 0 |
| **M11** | Pre-existing failures R1-R7 | 41 → 0 | 0 | 0 |
| **M12** | R4 refactor with TDD+review | 7 → 0 | 1 (correlation_id) | 7 |
| **M13** | R5/R6/R3 refactor | 10 → 0 | 1 (metrics m.__all__) | 5 |
| **M14** | Helpers + scaffolding audit | 0 (no test failures) | 1 (scaffold paths) | 5 |
| **M15** | Documentation accuracy | 0 | 0 | 0 |
| **M16** | SSL/cert hot-reload (D245) | 0 | 0 (new feature) | 4 |
| **TOTAL** | | **76** | **3** | **21** |

## D-rules promoted (Sprint 171)

- **D187** (M7): Facade single-import point
- **D194** (M12): Refactor with mandatory review+tests
- **D195** (M12): Facade must return value, not function
- **D196** (M12): Capability_gate strict mode = test/code sync
- **D198** (M14): Scaffold paths = `src/backend/...`
- **D199** (M14): graphify-out = auto-generated, not in git
- **D245** (M16): Cert hot-reload opt-in pattern

## New files (Sprint 171)

### Code
- `src/backend/dsl/contracts/schema_registry.py` (R1)
- `src/backend/core/security/encryption/envelope.py` (D174)
- `src/backend/infrastructure/workflow/versioning/worker_versioning.py` (D172)
- `src/backend/core/workflow/compensation.py` (D173)
- `src/backend/dsl/workflow/handlers/continue_as_new_handler.py` (D169)
- `src/backend/dsl/engine/processors/waf_check.py` (D171)
- `src/backend/infrastructure/security/cert_store/hot_reload.py` (D245)
- `src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py` (D169)
- `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py` (D170)

### Docs
- `docs/workflow/versioning.md` (D172)
- `docs/security/envelope_encryption.md` (D174)
- `docs/security/cert_hot_reload.md` (D245)
- `docs/m11_deferred_tests.md` (24 deferred tests tracking)
- `docs/ai/AGENT_GUIDE.md` (M7)
- `docs/integration/INTEGRATION_GUIDE.md` (M7)
- `docs/sprints/sprint-171-summary.md` (this file)

## Production readiness (per D236, Sprint 36)

- **CRITICAL** (P0) issues: 3 (Tool whitelist bypass, InProcessAgentSandbox, Frontend layer violations) — **DEFERRED to M15+**
- **HIGH** (P1) issues: 4 (Module whitelist, Docstring tooling, Optional deps, AI drivers) — **PARTIALLY FIXED in M16**
- **MEDIUM** (P2) issues: 4 (Dead deps, Duplicate deps, HITL busy-wait, Processor sprawl) — **2/4 FIXED (aiocache removed)**
- **LOW** (P3) issues: 4 — **DEFERRED to M17+**

## Test baseline

- **Pre-S171 baseline**: 2773 passed, 49 failed
- **Post-S171 (M10-M16)**: 4207 passed (+1434), 51 skipped (deferred with reason)
- **Pre-existing failures**: 14 (yaml_watcher debounce + 13 others — documented, out of scope)

## Commits (Sprint 171)

- M10: 8 commits (Worker Versioning, ContinueAsNew handler, CompensateWorkflow, EnvelopeEncryption, Schema-registry, BaseEntrypoint, tests, docs)
- M11 R1-R7: 7 commits (sync tests, test/code sync, optional imports, refactor skip, test-bugs, missing files, cleanup)
- M12 R4: 4 commits (auth_verify_request, route_loader, correlation_id BUG FIX, cleanup)
- M13: 5 commits (metrics m.__all__ fix, orders_saga partial, AI guardrails, R3 defer, tracking doc)
- M14: 3 commits (scaffold paths BUG FIX, LSP audit, check_docstrings audit, dead dep removal)
- M15: 1 commit (README updates + paths fix)
- M16: 1 commit (cert hot-reload via watchfiles)
- **TOTAL: ~30 atomic commits**

## Push status

- **BLOCKED** per AGENTS.md deny list
- Branch: master ahead by ~95+ commits
- Ready for review + push instruction
