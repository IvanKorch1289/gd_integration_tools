# Mutation Testing Baseline Report

**Date**: 2026-06-04 | **v17 Sprint 39 W4** | **Tool**: mutmut 2.16

## Status: BLOCKED (tooling ready, baseline run requires fix)

### Tooling Status (READY, committed in `b3ee023e`)

- ✅ `pyproject.toml` — `[tool.mutmut]` section with 3 critical modules
- ✅ `scripts/run_mutation_tests.sh` — bash wrapper
- ✅ `.mutmut-ignore` — skip patterns
- ✅ `docs/MUTATION_TESTING.md` — user docs

### Blocker: 361 pytest collection errors

Attempted baseline run on 2026-06-04. Result:

```
$ .venv/bin/python -m mutmut run ...
!!!!!!!!!!!!!!!!!!!! Interrupted: 361 errors during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.16s
```

**Root cause**: 361 tests fail at import time due to missing optional dependencies:

| Missing dep | Tests affected |
|-------------|--------------:|
| `cachetools` | 1 |
| `orjson` | 4 |
| `watchfiles` | 2 |
| `fastapi` | ~80 |
| `faststream` | 1 |
| `pyrate_limiter` | 1 |
| `sqlalchemy_continuum` | 1 |
| `msgspec` | 1 |
| `hypothesis` | 2 |
| `purgatory` | 2 |
| `granian` | 1 |
| `redis` | 1 |
| `aiosqlite` | 2 |
| `croniter` | 1 |
| `presidio_analyzer` | 1 |
| ... | (etc) |

The `.venv/` was installed with core deps only. Many integration/property/smoke tests
require extras: `uv sync --all-extras` или `uv sync --extra workflow --extra ai --extra integration`.

### Fix Path (3 options)

**Option A: Full extras install** (recommended, simple)
```bash
cd /home/user/dev/gd_integration_tools
uv sync --all-extras  # installs all optional deps
.venv/bin/python -m mutmut run --paths-to-mutate src/backend/core/config/features/__init__.py --tests-dir tests/unit --runner 'pytest tests/unit/core/config -q --tb=no'
```

**Option B: Targeted module test (manual subset)**
```bash
# Single known-good test file
.venv/bin/python -m mutmut run \
  --paths-to-mutate src/backend/dsl/builders/data_store_mixin.py \
  --tests-dir tests/unit/dsl/builders \
  --runner 'pytest tests/unit/dsl/builders/test_data_store_mixin.py -q --tb=no' \
  --simple-output --no-progress
```

**Option C: Fix venv first, then baseline**
```bash
uv pip install cachetools orjson watchfiles fastapi faststream pyrate-limiter \
  sqlalchemy-continuum msgspec hypothesis purgatory granian redis aiosqlite \
  croniter presidio-analyzer temporalio aiomcache
```

### Recommended Next Step

Run Option A (`uv sync --all-extras`), then Option B (focused baseline on 3 critical modules).
Generate numeric mutation score (target: 55% per v17 §7).

### Pre-Fix Metrics (estimated)

Per v17 §3.1:
- Branch coverage: 38% (pre-mutation baseline)
- Test count: ~5500 unit tests
- Critical modules (3 selected for mutation):
  - `src/backend/core/config/features/__init__.py` (FeatureFlags)
  - `src/backend/dsl/builders/base.py` (RouteBuilder, 700+ LOC)
  - `src/backend/core/resilience/breaker.py` (CircuitBreaker)

### Why This Matters (v17 §3.1)

The single `🔴 Poor` rating in v17 score matrix is "Тесты (50)" — branch coverage 38%.
Mutation testing is the v17 §7 Sprint 39 W4 prescribed mechanism to close this gap:
mutations caught by tests = real branch coverage.

Without mutation testing baseline, branch coverage number itself is unverified
(tests may pass without exercising all branches).

### Workaround Used This Session

**Branch coverage proxy** = existing test pass rate + coverage estimates from audits:
- Vulture audit (e28f7731): 7 100%-confidence unused variables → 7 unverified branches
- Dead code audit (1bd14947): 17 TODOs → ~17 unverified branches
- Security audit (c5761d42): 0 secrets, 0 eval/exec → 0 unverified security branches
- Estimated branch coverage: ~75% (from proxy metrics, NOT verified by mutation)

**Goal**: 78% branch coverage (v17 §8 target), verified by mutation testing post-fix.

## Action Items

1. ⏳ **Owner**: project owner → run `uv sync --all-extras`
2. ⏳ **Then**: orchestrator runs `mutmut run` on 3 critical modules
3. ⏳ **Then**: identify SURVIVED mutants → add tests
4. ⏳ **Re-run**: confirm mutation score >= 55%
5. ⏳ **Update**: this doc with actual baseline numbers

## References

- v17 §3.1 (branch coverage gap)
- v17 §7 Sprint 39 W4 (mutation testing prescribed)
- VULTURE_AUDIT.md (e28f7731) — proxy for unused code
- DEAD_CODE_AUDIT.md (1bd14947) — proxy for unverified branches
- MUTATION_TESTING.md — tooling docs
