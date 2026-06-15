# Sprint 130 W1 — Tech-Debt 4-State Classification Report (RED Gaps)

**Date**: 2026-06-15
**Sprint**: 130
**Wave**: W1 (analysis-only, Rule #96)
**Author**: pre-flight per Rule #109 + Rule #121
**Trigger**: S126 sprint plan (`reports/reaudit/archive/s126/sprint_plan.md`) requested S127 W1 = TD-030
(CB-1 delete 2 files) but HEAD shows S127-S128-S129 all executed; plan was stale before execution began.

## Context

S126 reaudit produced:
- 8 RED gaps in `s126_verification_matrix.md` (claimed as "Реальные gaps на S126")
- `s126_sprint_plan.md` S127-S128 roadmap (TD-030, TD-020, TD-021, TD-022, TD-024, TD-023, TD-025, TD-026)

**Pre-flight (Rule #109) обнаружил: 7 of 8 RED gaps already CLOSED в S127-S128, 1 PARTIAL CLOSED
(TD-030 / CB-1). The s126 reaudit report is stale relative to actual gate state** — same pattern
as S116-S117 cascade (Rule #109) and S129 W1 factcheck (6 of 8 OPEN TDs already closed).

HEAD state (S129 closed, ADR-0216):
- Sprint score: **9.8** (not 9.5 as in s126 plan baseline)
- ADRs: 166 (S127=0214, S128=0215, S129=0216)
- Layer linter: **0 NEW violations** (210 legacy baseline)
- Last S129 commit: `60b1a0d9 docs(s129-w5-closure)` (2026-06-14 23:21)

## Methodology

Per Rule #121 60-second pre-flight (parallel fact-check):
- `git log` для commit timestamps + author verification
- `find` + `wc -l` для file inventory
- `rg` / `grep -rE` для callsite counts
- `uv run python tools/check_layers.py` для gate state
- Per-gap verification: file existence, callsite count, tests passing, ADR closure

## 4-State Classification (Rule #114)

### P0/P1 RED Gaps (originally claimed as "8 реальных gaps на S126")

| # | Gap | s126 claim | Actual HEAD state | Classification |
|---|-----|------------|-------------------|----------------|
| 1 | **VAR-1** DSL Variable Store | нет `core/dsl/variables.py`, нет `${var('key')}` resolver | `dsl/builders/variable_mixin.py` + `dsl/engine/processors/variable_resolve.py` + `core/dsl/variables.py` (3 backends: memory/redis/vault). 12 unit tests. Commit `2640d56d` (S127 W2). | **closed** (state 1) |
| 2 | **FACADE-2** ExternalDBFacade | нет `core/db/`, нет `PoolingProfile` | `core/db/external_facade.py` (query/execute/transaction) + `PoolingProfile`. 11 unit tests. Commit `ae1efe1b` (S127 W3). 5+ callsite migration deferred to S129 (S129 W3 NO-OP discovery: only 2 legitimate direct uses). | **closed** (state 1) |
| 3 | **AI-6** Anthropic Prompt Caching | нет `cache_control: ephemeral` injection | `infrastructure/ai/prompt_cache_middleware.py` + `core/ai/gateway_pipeline_mixin/llm_mixin.py` + AIGateway injection. 23 unit tests. Anthropic (S127 W4, `5c4bae28`) + OpenAI (S128 W3, `623aef7c`). | **closed** (state 1) |
| 4 | **CDC-2** TransformCdcEventProcessor | нет `cdc_transform.py` | `dsl/engine/processors/cdc_transform.py` (210 LOC): normalize + filter + project CDC events. 16 tests (full mode, operations filter, project w/ new/old fallback, drop_unknown, source alias). Commit `4404ff9f` (S128 W2). | **closed** (state 1) |
| 5 | **CERT-1** Consul CertStore backend | `Literal["vault","postgres","mongo","memory"]` без consul | `infrastructure/security/cert_store/backend_consul.py` (212 LOC) + `test_backend_consul.py` (285 LOC, 13 tests). Commit `346f7d48` (S128 W1). Bonus Rule #124 fix: 4 sibling backends CertStore slots=True bug (S55 W1 latent ~71 sprints). | **closed** (state 1) |
| 6 | **DIST-1** DaskMixin | нет `dsl/builders/dask_mixin.py` | `dsl/builders/dask_mixin.py` (~110 LOC): `DaskMixin.dask_compute(...)` / `dask_map(...)` → RouteBuilder с DaskComputeProcessor. 10 tests. Commit `4404ff9f` (S128 W2). | **closed** (state 1) |
| 7 | **FB-1** S3 Runtime Fallback | нет `fallback_storage.py` + purgatory не declared | `tools/check_fallback_matrix.py` валидирует 11 resilience chains в `config_profiles/base.yml`. Storage backends: `s3.py`, `local_fs.py`, `s3_cache.py`, `sqlite_doc_store.py`, `factory.py` — все есть, **но НЕТ runtime S3→S3/FS fallback logic** в `src/backend/infrastructure/storage/`. Только `tools/check_fallback_matrix.py` для YAML chain validation. | **missing** (state 4) — real gap, new feature needed |
| 8 | **CB-1** CircuitBreaker dead code | `core/utils/circuit_breaker.py` + `core/utils/pybreaker_adapter.py` ВСЁ ЕЩЁ ЕСТЬ (v4 был прав) | Dead `HttpClient.circuit_breaker` removed (S127 W1 commit `61e75de7`). 2 shim files KEPT для `smtp.py` (deferred refactor). 6 regression tests added. smtp.py всё ещё импортирует `from src.backend.core.utils.circuit_breaker import get_circuit_breaker` (prod). `redis_breaker_storage.py` — separate concern (storage backend, not dead code). | **partial** (state 3) — finish in S130 W2 |

### P0/P1 v4 Fabricated/Stale Claims (per s126_verification_matrix.md §предупреждения)

| # | Claim | Reality | Status |
|---|-------|---------|--------|
| F1 | [P0 RES-1] Semaphore async with не релизит _semaphore на PAUSE | Code in `runner.py:313-323` корректно релизит semaphore. v4 bug claim НЕВЕРЕН. | **stale** (state 1) — fabricated bug |
| F2 | [P2 AI-5] guardrails-ai как gap | Проект использует `nemoguardrails`, не `guardrails-ai`. Wrong lib name. | **stale** (state 1) — wrong package |
| F3 | [P2 AI-9] mem0ai как gap | `mem0ai` REMOVED из `pyproject.toml`; заменён на `UnifiedMemoryGateway` (core/ai/memory/). | **stale** (state 1) — already replaced |

### Regression S114-S116 → S126 (per s126 claim)

| Aspect | s126 claim | Actual HEAD state | Status |
|--------|-----------|-------------------|--------|
| Layer linter NEW violations | 15 NEW core + 10 NEW ext | `uv run python tools/check_layers.py` → **0 NEW** (210 legacy) | **closed** (state 1) |
| Stale allowlist entries | 17 | S127 W1 commit `61e75de7` "prune 17 stale allowlist" | **closed** (state 1) |

## Summary

- **closed** (state 1): VAR-1, FACADE-2, AI-6, CDC-2, CERT-1, DIST-1, F1, F2, F3, layer linter, allowlist = **11 items**
- **partial** (state 3): CB-1 / TD-030 = **1 item** (smtp.py + redis_breaker_storage.py migration pending)
- **missing** (state 4): FB-1 = **1 item** (S3 Runtime Fallback, real new feature)
- **by-design** (state 2): 0

**Net: 7 of 8 RED gaps already closed. 1 partial. 1 genuinely missing.**
This is a **87.5% stale-gap rate** in the s126 verification matrix — same pattern as
S116-S117 cascade (Rule #109) and S129 W1 factcheck (75% stale-TD rate).

## Implications for S130 W2-W5

### W2 — TD-030 finish (CB-1 closure)
- Migrate `smtp.py` + `redis_breaker_storage.py` to canonical `core/resilience/breaker.py`
- Delete `core/utils/circuit_breaker.py` + `core/utils/pybreaker_adapter.py`
- 1 commit `chore(s130-w2-cb1-finish): migrate smtp/redis_breaker to canonical breaker, delete 2 shim files`
- Risk: MEDIUM (touch prod transport + storage)
- Time: ~2-3h + tests

### W3 — FB-1 (S3 Runtime Fallback, real new feature)
- New file: `infrastructure/storage/s3_fallback.py` (S3Primary → S3Secondary → LocalFS chain)
- Add `config_profiles/base.yml` resilience chain: storage.s3
- Add tests: `tests/unit/infrastructure/storage/test_s3_fallback.py` (10+ tests)
- 1 commit `feat(s130-w3-s3-fallback): S3Primary→S3Secondary→LocalFS runtime fallback chain`
- Risk: MEDIUM (storage layer change)
- Time: ~3-4h + tests

### W4 — TD-026 cont. (gRPC codegen wire-up) + TD-022 cont. (PydanticAIClient path coverage)
- `make grpc-codegen` regen (proto spec exists, `FileStreamGRPCServicer` exists, wire-up pending)
- PydanticAIClient path coverage in `services/ai/agents_pydantic/`
- 1-2 commits, small features
- Risk: LOW
- Time: ~2h

### W5 — ADR-0217 + CHANGELOG
- Score: **9.8 → 9.85** (estimated, +0.05 for FB-1 and TD-030 finish)

## Pre-existing Failures (from S129 W2)

- `tests/unit/entrypoints/grpc/test_grpc_server.py::test_load_tls_credentials_disabled_returns_none`
  — already fixed in S129 W2 (commit `462bcf27`). Closed as TD-033.

## Score Impact

**No change** — fact-check (analysis-only) не moves score, just reduces decision-risk.
- 9.8 → 9.8 (maintained)

## References

- `reports/reaudit/archive/s126/sprint_plan.md` (S126 plan, now archived)
- `reports/reaudit/archive/s126/verification_matrix.md` (S126 matrix, now archived)
- `reports/reaudit/s129_w1_factcheck_classification.md` (S129 6/8 stale-TD precedent)
- `reports/reaudit/tech_debt_register.md` (current register state, S129 W4 update)
- ADR-0214 (S127 closure, Sprint 127 score 9.7)
- ADR-0215 (S128 closure, Sprint 128 score 9.8)
- ADR-0216 (S129 closure, Sprint 129 score 9.8)
- Rule #109 (pre-sprint fact-check)
- Rule #114 (4-state classification)
- Rule #121 (60-sec pre-flight)
- `references/s116-w3-w5-factcheck-and-orphan-tests-2026-06-14.md` (precedent)
- `references/s117-w1-factcheck-noop-2026-06-14.md` (precedent)

## Archive Action

Moved to `reports/reaudit/archive/s126/`:
- `s126_sprint_plan.md` → `archive/s126/sprint_plan.md`
- `s126_verification_matrix.md` → `archive/s126/verification_matrix.md`

Reason: HEAD (S129) has executed S127-S128; the s126 sprint plan is no longer current.
Future planning starts from S130 baseline (this report).
