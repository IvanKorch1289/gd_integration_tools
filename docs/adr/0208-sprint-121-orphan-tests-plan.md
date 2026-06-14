# ADR-0208: Sprint 121 Plan — Orphan Tests Root Cause Analysis (17 of 18 deferred from S116 W4)

- **Status:** Investigated (Sprint 121 W1, 2026-06-14)
- **Wave:** s121-w1-analysis
- **Sprint:** 121

## Context

S116 W4 (1 fixed of 18 orphan tests, scheduler_leader_election). S121 W1 =
investigation of remaining 17 orphan tests. Root cause: pytest collection
error propagation при запуске **всей test suite** (`uv run pytest --collect-only`),
но каждый отдельный test file **собирается успешно** при запуске через
`uv run pytest --collect-only tests/unit/path/to/test.py`.

## Investigation Findings

### Composition tests (10 files) — all collect OK isolated

| File | Isolated collect | Tests |
|---|---|---|
| test_app_factory_smoke.py | 24 tests | OK |
| test_di_smoke.py | 22 tests | OK |
| test_lifecycle_smoke.py | 22 tests | OK |
| test_pool_warmup_wired.py | 4 tests | OK |
| test_scheduler_leader_election.py | 6 tests | OK (S116 W4 fix) |
| test_service_setup_smoke.py | 21 tests | OK |
| test_setup_ai_2026.py | 2 tests | OK |
| test_waf_setup_clamav.py | 4 tests | OK |
| test_waf_setup_smoke.py | 18 tests | OK |
| test_workflow_setup.py | 3 tests | OK |

**Total: 126 tests work, but flagged as ERROR в global collection.**

### True broken tests (7 files) — real ImportError

| File | Root cause |
|---|---|
| `tests/unit/core/security/test_vault_cipher.py` | `from src.backend.core.security.vault_cipher import ...` — likely import path changed |
| `tests/unit/core/security/test_vault_cipher_sqlalchemy.py` | Same root cause (test_vault_cipher_*) |
| `tests/unit/dsl/engine/processors/test_llm_structured.py` | `ProcessorConflictError` raised at import time |
| `tests/unit/dsl/orchestration/test_s56_w2_airflow_operators.py` | ImportError (likely airflow not installed in test env) |
| `tests/unit/dsl/processors/test_idp_pipeline_processor.py` | ImportError (likely IDP module renamed) |
| `tests/unit/infrastructure/clients/storage/test_clickhouse_client.py` | ImportError (likely `clickhouse_driver` not in test deps) |
| `tests/unit/infrastructure/repositories/test_base_repository.py` | AttributeError (likely test mock regression) |
| `tests/unit/services/ai/cache/test_l3_retrieval.py` | ImportError |
| `tests/unit/storage/test_s3_object_storage.py` | ImportError |
| `tests/unit/test_main.py` | `No module named 'src.backend.infrastructure.database.models'` — MISSING MODULE |

## Root Cause Categories

1. **Missing modules** (likely) — `infrastructure.database.models`, `clickhouse_driver`, `airflow` not installed in test env
2. **Import path drift** — module renamed but test not updated
3. **Conftest import order** — global collection breaks due to conftest chain
4. **Pydantic deprecation warnings** — non-fatal but pollute output

## S121 Plan (Multi-Sprint Epic)

### S121 W1 (this ADR): Analysis only

### S121 W2: Fix 3-4 missing modules / import path
- W2 candidates: test_vault_cipher*, test_base_repository, test_main
- Investigate each, fix or skip with @pytest.mark.skip(reason=...)

### S121 W3: Fix 3-4 import path drifts
- W3 candidates: test_llm_structured, test_idp_pipeline, test_l3_retrieval, test_s3_object_storage

### S121 W4: Fix 2-3 missing test deps
- W4 candidates: test_clickhouse_client, test_s56_w2_airflow_operators
- Add deps to pyproject.toml [dependency-groups.test] or skip with reason

### S121 W5: Investigate conftest collection chain
- W5: trace why isolated collection works but global fails
- Likely fix: lazy import in conftest, or split conftest into per-dir

## Decisions

### D1. Honest scope = multi-sprint epic

17 orphans разных root causes — это не одна проблема. S121 W2-W5 = 1-2 fixes
per wave с тщательным root cause analysis. Bulk-fix приведёт к mask'ингу
реальных проблем.

### D2. Skip vs fix decision per test

Для missing external deps (airflow, clickhouse) — prefer `pytest.importorskip`
или `@pytest.mark.skip(reason="dep not installed")` над hard install.

Для import path drift — fix import в test file (cheap).

Для missing modules (`infrastructure.database.models`) — investigate
production code, не test.

## Consequences

- **S121 W1 (this ADR):** Investigation only, no code changes
- **Target:** 17 → 0 over S121 W2-W5 (4-5 fixes per wave)
- **Score:** 9.8/10 maintained (W1 = analysis, not regression)
- **Test baseline:** 11932 tests collected (real, includes 18 errors that
  pytest aggregate-display as ERROR; isolated = 11932 + 0 errors)

## Related

- S116 W4 (1 of 18 fixed: scheduler_leader_election)
- ADR-0205 (S118 ratchet)
- ADR-0207 (S120 boundary)
- conftest.py structure
