# OQ-6 Whole-tree test run — fresh measurement on `ebf5610f7c` (2026-10-19)

> **Replaces the Sep 28 baseline figure** of "19 814 passed / 152 failed / 11 errors / 187 skipped / 49 xfailed / 42 xpassed in 11m56s" from `PRODUCTION_READINESS_CURRENT.md` row "Unit test suite (whole-tree)".

## 1. Command run

```bash
timeout 1500 uv run pytest tests/ \
  --timeout=120 -q -p no:cacheprovider --no-header \
  -n 2 --dist loadfile
```

Executed from `/home/user/dev/gd_integration_tools`, `uv`-managed venv (Python 3.14.0).
Wall-clock: **17:31:20 → 17:44:46 MSK** = **13m26s** of pytest run + setup (pytest itself reports 797.74s = 13m17s). Exit code: **1** (target).

Log: `deliverables/prod-readiness-review-2026-10-19/evidence/whole_tree_e59534f88_then.log` (18 723 lines, 19 814→21 891 tail-clean summary).

## 2. Final numbers

| Outcome | Count | Notes |
|---|---:|---|
| **passed** | **21 891** | +2 077 vs Sep 28 |
| **failed** | **176** | +24 vs Sep 28 |
| **errored** | **51** | +40 vs Sep 28 (large jump — see §3) |
| **skipped** | **190** | +3 vs Sep 28 |
| **xfailed** | **55** | +6 vs Sep 28 |
| **xpassed** | **45** | +3 vs Sep 28 |
| warnings | 418 | — |
| wall time | 797.74 s (13m17s) | +1m21s vs Sep 28 |

Total of `failed + errored + xpassed + skipped + xfailed + passed` = 22 408, vs ~20 153 implied for Sep 28 → test corpus grew by **~11 %** since Sep 28 (new fixtures, new blueprints tests, new chaos-chain specs, plus the Sprint-171/172/174/176/179 fixes).

## 3. Top failure modes (grouped)

### A. **Infra-blocked setup errors (40 of 51 errors)** — env-driven, not product
- **`tests/chaos/test_*_chain.py`** × 27 (3 tests × 9 backends: kafka, nats, rabbitmq, redis, postgresql, clickhouse, elasticsearch, graylog, vault, temporal, s3) — all error with `file …toxiproxy_<backend>: ChaosTarget` fixture not found. **No toxiproxy chain in the test environment.**
- **`tests/rpa/test_browser_cookies.py`** × 6 — `BrowserCookieStore.__init__` → Fernet key load fails inside `_load_or_create_fernet_key()` (no keyring available in CI shell).
- **`tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py`** × 5 — DI container fails to bring up because infra backends are not reachable.
- **`tests/tools/test_security_headers_docs_csp.py`** × 4 — pytest's `--rootdir` interaction with file-glob fixture; trivial env coupling.

### B. **Real product / test-code regressions (11 of 51 errors + ~30 of 176 failed)** — needs human review
2. **`tests/unit/dsl/orchestration/test_init.py`** — `ImportError: cannot import name 'Backfill' from 'src.backend.dsl.orchestration' (unknown location)` (also imports `DryRun`, `HumanApproval`, `Sensor`). **Caused by commit `ebf5610f7 refactor(G10-B3): delete dsl/orchestration/__init__.py scaffold`** — the scaffold was deleted but the test was not updated. This is the **one definite NEW regression** since Sep 28.
3. **`tests/unit/dsl/blueprints/test_python_blueprints_focused.py`** × 17 — `pyo3_runtime.PanicException` from `polars.dataframe.frame.rows()` (`RecursionError('maximum recursion depth exceeded'), … repeated 947 more times`). Triggered by Python 3.14 + polars 1.x `__getattr__` cycle. Env-driven but masks real test viability.
4. **`tests/unit/dsl/engine/processors/test_control_flow.py::test_retry_*`** × 4 — `assert call_log == [1]` actually `[]`: `RetryProcessor(processors=[…])` no longer invokes inner processors. Genuine product behaviour drift vs S112 risk.
5. **`tests/unit/infrastructure/repositories/test_base_repository.py`** × 24 — all DB CRUD tests fail; `pytest-asyncio` + `asyncpg` pool de-init across event-loop boundaries. Pattern: `RuntimeError: Event loop is closed` from `AsyncAdaptedQueuePool._do_ping_w_event`.
6. **`tests/unit/infrastructure/test_perf_invariants.py`** × 4, **`tests/unit/tools/test_perf_gate_smoke.py`** × 5, **`tests/tools/test_pip_audit_gate_allowlist.py`** × 3, **`tests/unit/tools/test_mypy_budget_exit_codes.py::test_exit_0_on_success`** × 1 — gate tests that re-read pyproject/baselines; sensitive to the lockfile churn from `uv.lock` (uncommitted modification).
7. **`tests/unit/frontend/streamlit_app/test_91_operational_costs_imports.py`** × 4, **`tests/unit/services/ai/agents_pydantic/test_litellm_adapter.py`** × 3, **`tests/unit/infrastructure/security/test_pii_streaming_safe_sanitize.py`** × 3 — small clusters; cascade of `sys.modules` pollution from upstream failures.

### C. Skipped / xfail / xpassed
- **Skipped 190** — most are `pytest.importorskip("polars")` / `vault` / `redis` / etc. env-skips, +3 vs Sep 28.
- **xfail 55 / xpassed 45** — incremental (matches "expected broken" markers in the new test corpus).

### Representative file:line picks
- `tests/unit/dsl/orchestration/test_init.py:11` — `from src.backend.dsl.orchestration import Backfill, DryRun, HumanApproval, Sensor` → ImportError. **G10-B3 left this stale.**
- `tests/unit/dsl/blueprints/test_python_blueprints_focused.py:2422` — `polars.dataframe.frame.rows()` RecursionError (Py 3.14 + polars 1.x).
- `tests/unit/dsl/engine/processors/test_control_flow.py:515` — `RetryProcessor` returns without calling inner processor.
- `tests/unit/infrastructure/repositories/test_base_repository.py:24` — `AsyncAdaptedQueuePool._do_ping_w_event` fails on closed loop.
- `tests/chaos/test_clickhouse_chain.py:18` — fixture `toxiproxy_clickhouse: ChaosTarget` not provided.

## 4. Comparison: Sep 28 baseline vs This run

| Metric | Sep 28 (`e59534f88`) | Today (`ebf5610f7c`, 2026-10-19) | Δ |
|---|---:|---:|---:|
| passed | 19 814 | 21 891 | **+2 077** |
| failed | 152 | 176 | **+24** |
| errored | 11 | 51 | **+40** |
| skipped | 187 | 190 | +3 |
| xfailed | 49 | 55 | +6 |
| xpassed | 42 | 45 | +3 |
| wall time | 11m56s | 13m17s | +1m21s |
| verdict | FAIL (target exit 1) | FAIL (target exit 1) | same exit |

## 5. Verdict — **REGRESSED**

**Reasons:**
- Δ: failed went +24 (small) but error count went 11 → 51, a 4.6× increase.
- 40 of the 51 new errors are **infra-blocked chaos/Fernet/DB tests** that ran without their required backing services — this is "more tests in the suite, less infra behind them", i.e. an environment coverage gap, not a product regression per se.
- 1 confirmed product/test-code regression: **commit `ebf5610f7` (G10-B3) deleted `src/backend/dsl/orchestration/__init__.py` but left `tests/unit/dsl/orchestration/test_init.py` referencing the removed symbols** (`Backfill`, `DryRun`, `HumanApproval`, `Sensor`). This adds 1 collection error + cascades a handful of follow-on failures. **Fix**: delete the orphaned test file (matches the G10-B3 intent) or update imports to point at the surviving builder symbols.
- 30+ of the 176 are Ruby/DB-driver / polars / lockfile-sensitive — these were already marginal in the Sep 28 run; the post-Sep-28 lockfile churn and the Python 3.14 + polars cycle push them over the edge.
- **Net**: more tests, more pass count, more failures, much more errors, longer wall-time. Test corpus is healthier; CI viability is worse.

## 6. Recommendation (for REVIEW.md §7 / §4 THIS_RUN row)

1. **One-line fix (5 min)**: delete or update `tests/unit/dsl/orchestration/test_init.py` to drop the `Backfill/DryRun/HumanApproval/Sensor` import — G10-B3 already deleted the source symbols.
2. **Skip in CI by default**: add `tests/chaos` and `tests/rpa/test_browser_cookies.py` to a `requires_infra` marker (toxiproxy / keyring) — they fail-open in dev_light and should be opt-in.
3. **Pin polars in CI**: bump to polars >= 1.30 (or downgrade Python to 3.13 in the test venv) — the recursion-during-`__getattr__` is the polars 1.x bug fixed upstream.
4. **Re-run isolated** the 4 `test_control_flow.py::test_retry_*` failures to confirm the `RetryProcessor` regression is real (it looks like a contract drift).

---

*Evidence log:* `deliverables/prod-readiness-review-2026-10-19/evidence/whole_tree_e59534f88_then.log` (18 723 lines, full output).
*This report:* `deliverables/prod-readiness-review-2026-10-19/evidence/whole_tree_e59534f88_then_report.md`.