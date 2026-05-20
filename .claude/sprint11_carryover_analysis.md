# Sprint 11 Closure — S10/S9 Carryover Analysis

**Date**: 2026-05-20  
**Gate Status**: pre-prod-check → 6 FAIL (gates 01/03/04/06/08/11), 6 SKIP, 8 OK  
**Target**: 20/20 passing for S11 closure  

---

## Problem 1: uv-resolver cascade (gates 01/04/06/08)

**Issue**: `gd-advanced-tools[ai-voice]` pins `openai-whisper>=20240930,<2` + `TTS>=0.22,<1` → CONFLICTS with `mlflow` indirect deps through dask.

**File references**:
- `pyproject.toml:207-209` — ai-voice extra (openai-whisper, TTS)
- `pyproject.toml:198-200` — ai-model-registry extra (mlflow, huggingface_hub)
- `pyproject.toml:85` — base `pyarrow>=20.0.0,<25.0.0`

**Root cause**: TTS/whisper + mlflow diverge on scipy/numpy/pyarrow transitive versions. No `[tool.uv.constraints]` to pre-narrow.

**Reproduction**:
```bash
python -m pip install "gd-advanced-tools[ai-voice,ai-model-registry]" --python-version 3.14
# Or: uv pip compile --extra ai-voice --extra ai-model-registry
```

**Fix options**:
- A: Pin `TTS>=0.24` (newer, better scipy alignment)
- B: Restrict mlflow to <2.17
- C: Add `[tool.uv.constraints]` section for resolution order

---

## Problem 2: Layer violations (25 NEW, gate 03)

**File references** (critical violations):
- `src/backend/core/auth/quotas.py:27` → imports `src.backend.services.billing.quotas_service` (**core → services VIOLATION**)
- `src/backend/core/ai/fs_facade.py` → imports from `src.backend.services.ai.document_parsers` (**core → services**)
- `src/backend/core/messaging/dlq.py` → imports from `src.backend.infrastructure.messaging.dlq_base` (**core → infrastructure**)
- `src/backend/core/plugin_runtime/compat_checker.py` → imports from `src.backend.services.plugins.manifest_v11` (**core → services**)
- `src/backend/entrypoints/api/v1/endpoints/admin_capabilities.py` → imports from `src.backend.infrastructure.audit.event_log` (**entrypoints → infrastructure**)

**Violation pattern**: 
- core→services (11 violations)
- core→infrastructure (8 violations)
- entrypoints→infrastructure (5 violations)
- infrastructure→services (1)

**Command to reproduce**:
```bash
python -m tools.check_layers 2>&1 | head -60
```

**Root cause**: Wave S8-S10 feature additions. Example: quotas.py added business logic call to billing.quotas_service in K1 W6, breaking layering.

**Fix strategy**:
1. Extract interface (Protocol) → core/auth/quotas_protocol.py
2. Move implementation → infrastructure/billing/quotas_impl.py or services/billing/
3. Inject via svcs (DI container)

---

## Problem 3: Docstring coverage CLI args (gate 11)

**File references**:
- `tools/check_docstrings.py:1-30` — argument parser
- `tools/check_docstrings_allowlist.txt:1` — baseline amnesty (34KB, valid)

**Issue**: pre-prod gate calls `check_docstrings` without paths:
```
check_docstrings.py: error: требуется хотя бы один из: [paths] [--strict] [--update-allowlist]
```

**Root cause**: Gate invocation line missing positional args. Should be:
```bash
python -m tools.check_docstrings src/backend/core src/backend/dsl/engine src/backend/core/interfaces
```

**File to fix**: `tools/checks/pre_prod_check.py:162` — add paths to invocation.

**New docstring violations**: ~100 in core/auth, core/ai, core/di/providers.py (see problem #5 regression list).

---

## Problem 4: Startup time regression (OK but at limit)

**File references**:
- `.startup-time-baseline.json` — baseline = 1.0561s
- `tools/checks/startup_time.py:34-36` — MAX_TOTAL = 3.0s, REGRESSION_TOLERANCE = 30% → limit 1.373s

**Issue**: Measured 1.8s in S8-S10, regression margin ok (1.8 < 3.0). But trending toward limit.

**Root cause**: Wave S8-S10 lazy imports added overhead in:
- `src/backend/core/ai/` (AIWorkspaceManager, Sandbox init)
- `src/backend/infrastructure/cache/rag/` (semantic.py imports)
- `src/backend/services/ai/` (embedding_providers, langmem lazy loads)

**Command**:
```bash
python tools/checks/startup_time.py 2>&1 | tail -10
```

**Status**: Currently PASS (pre-prod gate shows "OK (1.8s)"). If >1.373s next measure, need ratchet or defer imports.

---

## Problem 5: Test collection ERRORs (91 pre-existing, not test failures)

**Categories** (28 import errors blocking collection):

1. **test_rag_citations.py:10** — `ImportError: cannot import 'RAGCitation' from rag_service`
   - File: `src/backend/services/ai/rag_service.py` (refactored in S10 RAG wave, export missing)

2. **cache/backends** — `ModuleNotFoundError: No module named 'cache'`
   - Import path mismatch (likely `src.cache` vs `src.backend.cache`)

3. **security/pii/test_streaming.py** — `ImportPathMismatchError`
   - Namespace conflict (src/security vs src.backend.security)

4. **tests/chaos/** (11 tests) — Container/fixture deps

5. **tests/unit/api/** (5 tests) — ActionSpec tier imports

**Reproduction**:
```bash
python -m pytest tests/unit/services/ai/test_rag_citations.py --collect-only 2>&1
python -m pytest tests/unit/cache/ --collect-only 2>&1 | grep -i error
```

**Scope**: ~200 LOC fixes across test files + 3 module setup files.

---

## Problem 6: WAF allowlist baseline (PASS, verify)

**File reference**:
- `tools/check_waf_coverage.py` — no explicit allowlist persistence

**Current output**:
```bash
python -m tools.check_waf_coverage 2>&1
# WAF coverage OK: 0 violations
```

**Baseline** (from MEMORY.md Wave K1 S1):
- Vault×2 (fs.write, code.execute)
- ClickHouse (query external)
- Bots×2 (RPA, LLM)
- OPA (policy)
- express_chain (legacy)

**Verify**:
```bash
grep -r "ALLOWLIST\|allowlist" tools/checks/check_waf_coverage.py
cat tools/checks/pre_prod_check.py | grep -A 5 "WAF coverage"
```

---

## Problem 7: SBOM generation (WORKING now, gate fails due to cascade)

**File reference**:
- `tools/checks/generate_sbom.py:108`

**Status**: Manual run ✓ OK (outputs `dist/sbom/sbom.cdx.json`).

**Root cause**: Pre-prod gate fails because:
1. uv-resolver cascade from ai-voice conflict (Problem 1)
2. Dependency resolution fails before SBOM generation runs
3. Downstream gates (bandit, coverage, ruff) fail on same resolver error

**Fix**: Resolve Problem 1 (uv-resolver) first; SBOM will auto-pass.

---

## Summary by Sprint 11 Priority

| Gate | Status | LOC | Blocker? | Files |
|------|--------|-----|----------|-------|
| 01 coverage | FAIL | 5–10 | YES | pyproject.toml |
| 03 layers | FAIL | 400–600 | YES | 25 core/entrypoints/infrastructure files |
| 04 ruff strict | FAIL | — | cascades from 01 | pyproject.toml |
| 06 SBOM | FAIL | — | cascades from 01 | pyproject.toml |
| 08 bandit-tls | FAIL | — | cascades from 01 | pyproject.toml |
| 11 docstring | FAIL | 1–2 | NO | tools/checks/pre_prod_check.py |
| 19 startup | OK | 0 | NO | .startup-time-baseline.json (optional ratchet) |
| Tests | 91 ERR | 200–250 | NO | test_rag_citations.py, cache/__init__.py, security/ |

---

## Sequential Fix Order (S11)

1. **BLOCKER** — Problem 1: Resolve ai-voice + mlflow uv-resolver (5 min, 1 commit)
   - Then gates 01/04/06/08 auto-resolve
   
2. **QUICK** — Problem 3: Fix docstring gate args (1 min, 1 line change)

3. **CORE ARCH** — Problem 2: Layer violations (2–3h, 5–6 commits group-by-direction)
   - Extract Protocols → core/
   - Move impls → infrastructure/
   - Wire via DI
   
4. **TEST SETUP** — Problem 5: Fix import paths (30–45 min, 3 commits)

5. **VALIDATION** — Rerun `make pre-prod-check` → target 20/20

**Estimated total time**: 3.5–4 hours, ~12 commits.
