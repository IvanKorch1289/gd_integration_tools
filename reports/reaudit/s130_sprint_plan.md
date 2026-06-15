# Sprint 130 — "CB-1 finish + S3 Fallback + gRPC wire-up" (5 waves)

**Date**: 2026-06-15
**Sprint**: 130
**Author**: post-S129 (ADR-0216), score 9.8
**Source**: S130 W1 fact-check (`reports/reaudit/s130_w1_factcheck_classification.md`)

**Goal:** Close TD-030 (P3 quick win finish) + FB-1 (P1 new feature) + TD-026 cont. (P2 wire-up)
+ TD-022 cont. (P3 path coverage) + finish S130 backlog.

**Score:** 9.8 → 9.85 (estimated)

**Anti-bloat guardrails:** ≤ 5 waves, ≤ 1 day per feature, ≤ 3 sprints per planning cycle.

---

## W1 — Fact-check + sync (DONE in this commit)

| Aspect | Detail |
|--------|--------|
| Items | S126 reaudit sync + TD-030 state reclassification (PARTIAL → CLOSED-in-progress) |
| Files changed | `reports/reaudit/s130_w1_factcheck_classification.md` (new), `reports/reaudit/s130_sprint_plan.md` (new), `reports/reaudit/archive/s126/{sprint_plan.md, verification_matrix.md}` (moved) |
| Commit | `docs(s130-w1-factcheck): fresh S130 baseline + archive stale s126 files (87.5% stale-gap rate)` |
| Risk | NONE (analysis-only + file moves) |
| Time | ~30 min |

**W1 verification:** `git log --oneline -1` shows the docs commit; archive dir contains 2 s126 files; new fact-check + sprint plan present.

---

## W2 — TD-030 finish: CB-1 closure (smtp + redis_breaker migration)

| Aspect | Detail |
|--------|--------|
| Items | TD-030 (P3 PARTIAL → CLOSED) |
| Files to change | `infrastructure/clients/transport/smtp.py` (replace `from src.backend.core.utils.circuit_breaker import get_circuit_breaker` → `from src.backend.core.resilience.breaker import ...`), `infrastructure/resilience/redis_breaker_storage.py` (same), `core/utils/circuit_breaker.py` (DELETE), `core/utils/pybreaker_adapter.py` (DELETE), `tests/unit/core/utils/test_circuit_breaker_removed.py` (NEW regression test) |
| Files to verify | All callsites of deleted modules (rg `from .*core\.utils\.circuit_breaker\|core\.utils\.pybreaker_adapter` → 0) |
| Canonical target | `core/resilience/breaker.py` (existing since S100) |
| New tests | Regression test that imports of deleted modules raise `ModuleNotFoundError`; canonical breaker smoke test on smtp path |
| Commit | `chore(s130-w2-cb1-finish): migrate smtp + redis_breaker to canonical breaker, delete 2 shim files` |
| Risk | MEDIUM (touches prod transport smtp.py + storage redis_breaker_storage.py) |
| Time | ~2-3h + tests |

**W2 verification:**
- `rg "from .*core\.utils\.circuit_breaker\|core\.utils\.pybreaker_adapter" src/ tests/ extensions/` = 0
- `uv run pytest tests/unit/infrastructure/clients/transport/test_smtp.py` = green
- `uv run pytest tests/unit/infrastructure/resilience/test_redis_breaker_storage.py` = green
- `tools/check_layers.py` shows 0 NEW violations

---

## W3 — FB-1: S3 Runtime Fallback (real new feature)

| Aspect | Detail |
|--------|--------|
| Items | FB-1 (P1 missing — REAL at S130) |
| Files to create | `infrastructure/storage/s3_fallback.py` (S3Primary → S3Secondary → LocalFS chain class), `tests/unit/infrastructure/storage/test_s3_fallback.py` (10+ tests) |
| Files to modify | `infrastructure/storage/factory.py` (integrate fallback chain), `config_profiles/base.yml` (add `resilience.fallbacks.storage` entry) |
| API | `S3FallbackChain(primary: S3Client, secondary: S3Client | None, local: LocalFS, timeout: float = 5.0)`. `async get(key) -> bytes | None`: try primary → secondary → local. `async put(key, data) -> str`: try primary → secondary. Records metrics per hop. |
| Validation | `tools/check_fallback_matrix.py` уже валидирует 11 chain entries; storage.s3 will be #12. |
| New tests | Primary success; primary fail → secondary success; primary + secondary fail → local success; all fail → raises; metrics recorded per hop; timeout per hop; circuit-breaker integration. |
| Commit | `feat(s130-w3-s3-fallback): S3Primary→S3Secondary→LocalFS runtime fallback chain (FB-1)` |
| Risk | MEDIUM (storage layer change, but additive — no breaking changes to existing S3 clients) |
| Time | ~3-4h + tests |

**W3 verification:**
- `tools/check_fallback_matrix.py` shows 12 chains (was 11)
- `uv run pytest tests/unit/infrastructure/storage/test_s3_fallback.py` = 10+ green
- No regression in existing `test_factory.py`, `test_s3.py`, `test_local_fs.py`

---

## W4 — TD-026 cont. (gRPC codegen wire-up) + TD-022 cont. (PydanticAIClient path coverage)

| Aspect | Detail |
|--------|--------|
| Items | TD-026 cont. (P2 wire-up) + TD-022 cont. (P3 path coverage) |
| Files to change | `Makefile` (verify/add `grpc-codegen` target), `proto/...` (regen if missing), `services/ai/agents_pydantic/adapter.py` (extend PydanticAIClient coverage), `core/ai/pydantic_ai_client.py` (add 2-3 methods) |
| New tests | gRPC FileStream integration smoke (1-2 tests), PydanticAIClient extended path (3-4 tests) |
| Commit(s) | `feat(s130-w4-grpc-wireup): grpc-codegen regen + FileStream wire activation (TD-026 cont.)`, `feat(s130-w4-pydantic-ai-path): extend PydanticAIClient path coverage (TD-022 cont.)` |
| Risk | LOW (proto regen is mechanical; PydanticAIClient extension is additive) |
| Time | ~2h total |

**W4 verification:**
- `make grpc-codegen` regenerates successfully
- `uv run pytest tests/unit/entrypoints/grpc/test_file_stream.py` = green
- `uv run pytest tests/unit/services/ai/agents_pydantic/` = green

---

## W5 — ADR-0217 + CHANGELOG + INDEX closure

| Aspect | Detail |
|--------|--------|
| Items | Sprint closure doc |
| Files to create | `docs/adr/0217-sprint-130-closure.md` |
| Files to modify | `CHANGELOG.md` (S130 section), `docs/adr/INDEX.md` (add 0217) |
| Commit | `docs(s130-w5-closure): ADR-0217 sprint closure + CHANGELOG + INDEX (166 → 167)` |
| Risk | NONE |
| Time | ~15 min |

**W5 verification:** `git log --oneline -5` shows S130 closure commit; ADR-0217 exists; CHANGELOG/INDEX updated.

---

## Cumulative Targets

By S130 W5:
- TD-030 CLOSED (smtp + redis_breaker migrated, 2 shim files deleted, regression test added)
- FB-1 CLOSED (S3FallbackChain implemented, 12 chains in check_fallback_matrix, 10+ tests)
- TD-026 cont. CLOSED (gRPC codegen wire-up active)
- TD-022 cont. CLOSED (PydanticAIClient path extended)
- Score: 9.8 → 9.85
- ADRs: 166 → 167

## S131+ Deferred

- TD-013 (Streamlit feature-grouping, 6+ hours) — needs dedicated sprint
- TD-008 (audit facade split 394 LOC) — P2, deferred S131+
- TD-010, TD-011, TD-014, TD-015, TD-016 — various P2/P3, deferred

## Anti-bloat Self-Check

- 5 waves, 4 features + 1 closure (Rule: 4 work + 1 closeout per sprint) ✓
- W2: 1 commit, 1 feature, ≤ 1 day ✓
- W3: 1 commit, 1 feature (with tests), ≤ 1 day ✓
- W4: 1-2 commits, 2 small features, ≤ 1 day ✓
- W1 + W5: docs/analysis only, 0 risk ✓
- Sprint fits in ≤ 1 week (Rule: ≤ 3 sprints per planning cycle) ✓
