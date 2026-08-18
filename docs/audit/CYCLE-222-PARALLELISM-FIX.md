# Cycle 222 — test_admin_parallelism fix (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 222)
**Scope:** Fix 4 pre-existing test failures (Ponytail-win).

---

## TL;DR

| Item | Status | Result |
|---|---|---|
| Pre-existing failures fixed (cycle 222) | ✅ DONE | 4 → 0 (test_admin_parallelism 6/6 PASS) |
| Atomic commit | ✅ DONE | 1 file, 7 lines changed |
| Other pre-existing failures | ⏸️ DEFERRED | test_rag_endpoint_pii (different class) |

**1 commit** (`6e605311`): +7/-7 LOC.

---

## 1. Root cause

Tests patched `src.backend.dsl.route_loader.registry` — but the
function imports from `src.backend.dsl.registry`. Per D-AUDIT-11701
(cycle 117), `route_loader.registry` module doesn't exist
(canonical path is `src.backend.dsl.registry`, re-export from
`src.backend.dsl.commands.registry`).

```diff
- with patch.dict(sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}):
+ with patch.dict(sys.modules, {"src.backend.dsl.registry": fake_module}):
      result = await mod.parallelism_report("test-route")
```

**6 patches** in test file all use the wrong path.

---

## 2. Verification

### Before

```
tests/unit/entrypoints/api/v1/endpoints/test_admin_parallelism.py:
- test_parallelism_report_with_registry  FAILED (200 вместо 200, но steps=0)
- test_parallelism_report_route_not_found  FAILED (200 вместо 404)
- test_parallelism_report_registry_import_error  FAILED
- test_parallelism_report_registry_exception  FAILED
- test_parallelism_report_http_200  FAILED
- test_parallelism_report_http_404  FAILED
```

### After

```
tests/unit/entrypoints/api/v1/endpoints/test_admin_parallelism.py:
- test_parallelism_report_with_registry  PASSED
- test_parallelism_report_route_not_found  PASSED
- test_parallelism_report_registry_import_error  PASSED
- test_parallelism_report_registry_exception  PASSED
- test_parallelism_report_http_200  PASSED
- test_parallelism_report_http_404  PASSED

6 passed, 1 warning in 0.38s
```

🎉 **4 pre-existing failures → 0**.

---

## 3. Other pre-existing failures (deferred to cycle 223+)

`tests/unit/entrypoints/api/v1/endpoints/test_rag_endpoint_pii.py`:
- 3 failures (`TestUploadRoutesThroughRagIngestService`)
- 4 xfailed (expected failures, forward-looking TDD)

The rag_endpoint_pii failures are in a different test class with
`AsyncMock` + `monkeypatch` + `patch.object` patterns. Per Ponytail
"shortest working diff wins", they're deferred to cycle 223+ as
a separate concern.

---

## 4. Артефакты

- `tests/unit/entrypoints/api/v1/endpoints/test_admin_parallelism.py` (+7/-7)
- `docs/audit/CYCLE-222-PARALLELISM-FIX.md` (this file)

**HEAD**: `6e605311`

---

## 5. Status summary (cycles 201-222)

- **35 atomic commits**, +6700+ LOC, 50+ new tests, 0 regressions
- **NEW-3** at 99% (mount path mismatch deferred)
- **gRPC Cython** real RPC deferred (lock file change requires approval)
- **Cycle 222**: 4 pre-existing test failures fixed (test_admin_parallelism)
- **Remaining pre-existing failures**: test_rag_endpoint_pii (3 failures) — deferred
