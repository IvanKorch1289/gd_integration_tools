# Cycle 6 — D-AUDIT-607 report

## Task

- **ID:** T-C6-07-HITL-AUTH
- **Finding:** API-P0-001
- **Scope:** `src/backend/entrypoints/api/v1/endpoints/hitl.py`
- **Marker:** `cycle-6/D-AUDIT-607`

## Status

**IMPLEMENTED / TARGET TESTS PASS.**

Global `cycle-1-preflight.sh` remains exit `1` because the shared working tree was already dirty and `uv.lock` had a pre-existing 45-line diff. The task did not modify `uv.lock`; its churn stayed **45 lines before and after**. Security caps remain unchanged: **175 legacy / 0 new** layer violations and **27** active allowlist IDs.

## Changes

1. Added router-level fail-closed dependency:
   `dependencies=[Depends(require_permission("hitl.resolve"))]`.
2. Added `401` when auth context is absent and `403` when `hitl.resolve` is absent.
3. Restricted pending/history queries to the authenticated tenant.
4. Added ownership checks before reading or resolving a HITL signal; cross-tenant access returns `403`.
5. Added regression tests for unauthenticated, cross-tenant, and own-tenant resolve paths.

## Diff stat

```text
src/backend/entrypoints/api/v1/endpoints/hitl.py       | +82 -8
tests/unit/entrypoints/api/v1/endpoints/test_hitl.py   | +93 -0
TOTAL                                                   | +175 -8
```

## Verification

### Target tests

Command:

```bash
.venv/bin/python -m pytest tests/unit/entrypoints/api/v1/endpoints/test_hitl.py --no-cov -q
```

Output:

```text
...                                                                      [100%]
3 passed, 1 warning in 2.36s
```

The warning is the existing Starlette `TestClient` deprecation warning for `httpx`.

### Lint / format

```text
.venv/bin/python -m ruff check ...
All checks passed!

.venv/bin/python -m ruff format --check ...
2 files already formatted
```

### Docstring gate

Command:

```bash
make check-docstrings MAX_ALLOWED=0
```

Output:

```text
Total: 0 missing docstrings in 0 files
Files scanned: 840
docstring policy OK
```

### Layer / allowlist caps

```text
Нарушений: 0 новых  (файлов: 2278; baseline: 175 legacy)
allowlist active IDs: 27
```

### Mandatory preflight

Before changes:

```text
[OK] layer checker — 0 new, 175 legacy
[OK] allowlist active IDs — 27
[OK] docstring gate — 0 missing
[FAIL] working tree — 15 entries
[FAIL] uv.lock churn — 45 lines
[OK] s3.py untouched
exit 1
```

After changes (concurrent shared-tree activity present):

```text
[OK] layer checker — 0 new, 175 legacy
[OK] allowlist active IDs — 27
[OK] docstring gate — 0 missing
[FAIL] working tree — 40 entries
[FAIL] uv.lock churn — 45 lines
[OK] s3.py untouched
exit 1
```

The HITL task itself adds two source/test paths plus this report; it does not rewrite or remove concurrent/pre-existing changes.

## Protected files

No task changes in:

- `.security/pip-audit-allowlist.txt`
- `uv.lock`
- `src/backend/infrastructure/storage/s3.py`
- `tools/blue_green.sh`
- `tests/unit/tools/test_blue_green_switch.py`
- `src/backend/services/ai/gateway_adapter.py`
