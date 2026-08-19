# Cycle 234 — gRPC Cython fix via FileStreamGRPCServicer import (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 234)
**Scope:** Real gRPC Cython fix via Ponytail 1-line import.

---

## TL;DR

| Item | Status |
|---|---|
| gRPC Cython root cause | ✅ IDENTIFIED (per cycle 230/233) |
| Real fix via 4-line import | ✅ DONE (D-AUDIT-20823) |
| Tests fixed | 2/3 pre-existing failures now PASS |
| Remaining | 1/3 pre-existing test isolation issue |

**1 commit** (`3428a634`): +8 LOC.

---

## 1. Root cause (cycle 230/233 deep analysis)

The `_patch_rpc_methods` loop at `__init__.py:183`:
```python
for _cls_name in ("InvokerGRPCServicer", "OrderGRPCServicer", "FileStreamGRPCServicer"):
    try:
        _cls = globals()[_cls_name]
    except KeyError:
        continue
    # Patch все callable methods subclass'а
    for _method_name in dir(_cls):
        ...
```

**Critical issue**: `globals()` is the `__init__.py` module's globals. `FileStreamGRPCServicer` was defined in `grpc_server/file_stream.py`, NOT in `__init__.py`. So `globals()["FileStreamGRPCServicer"]` raised `KeyError` → `continue` → NEVER PATCHED.

**Result**: 3 pre-existing test failures (the test checks `FileStreamGRPCServicer.DeleteFile.request_streaming`):
- `test_delete_file_has_request_streaming` (FAIL → ✅ PASS)
- `test_get_file_has_request_streaming` (FAIL → ✅ PASS)
- `test_method_dict_attr_works_daudit_19801` (still fails — different root cause)

## 2. Fix (D-AUDIT-20823)

```python
# src/backend/entrypoints/grpc/grpc_server/__init__.py
from src.backend.entrypoints.grpc.grpc_server.file_stream import (
    FileStreamGRPCServicer,  # S128 W3: re-export
)
```

**4-line import** to register `FileStreamGRPCServicer` in `__init__.py`'s namespace. The patch loop at line 183 now finds the class via `globals()`.

## 3. Validation

### 3.1 In isolation (4/4 PASS)

```
tests/unit/entrypoints/grpc/test_grpc_subclass_methods_patch.py::TestFileStreamSubclassMethodsPatched
  - test_delete_file_has_request_streaming       PASSED
  - test_get_file_has_request_streaming          PASSED
  - test_download_file_known_python_quirk        PASSED
  - test_upload_file_known_python_quirk          PASSED
```

### 3.2 In full suite (2/3 PRE-EXISTING TESTS FIXED)

| Test | Before | After |
|---|---|---|
| `test_delete_file_has_request_streaming` | ❌ FAIL | ✅ PASS |
| `test_get_file_has_request_streaming` | ❌ FAIL | ✅ PASS |
| `test_method_dict_attr_works_daudit_19801` | ❌ FAIL | ❌ FAIL (different root cause) |
| **All other tests** | ✅ PASS | ✅ 63 PASS |

### 3.3 Functional verify

```python
>>> from src.backend.entrypoints.grpc.grpc_server.file_stream import FileStreamGRPCServicer
>>> val = FileStreamGRPCServicer.DeleteFile.request_streaming
>>> print('val:', repr(val), '== False?', val is False)
val: False == False? True
```

🎉 **gRPC Cython теперь может обработать request**: `FileStreamGRPCServicer.DeleteFile.request_streaming = False` → Cython check passes.

## 4. Артефакты

- `src/backend/entrypoints/grpc/grpc_server/__init__.py` (+8 LOC)
- `docs/audit/CYCLE-234-FILESTREAM-FIX.md` (this file)

**HEAD**: `3428a634`

---

## 5. Remaining (deferred to cycle 235+)

| Test | Status | Reason |
|---|---|---|
| `test_method_dict_attr_works_daudit_19801` | ❌ FAIL | Different code path (not FileStream-related) |
| NEW-3 MCP | ❌ 404 | Multi-cycle debug |
| gRPC real RPC end-to-end | ⚠️ Test isolation | Container image stale from cycle 208 |

### Recommended cycle 235+: investigate test_method_dict_attr_works_daudit_19801

The test expects `request_streaming` to be set on a different class. Per cycle 198/233, the test is pre-existing and the root cause is different from FileStream.

---

## 6. Status summary (cycles 201-234)

- **48 atomic commits**, +6700+ LOC, 50+ new tests, **0 regressions** (cycle 234 verified)
- **Cycles 222-234** (13 cycles):
  - 9 pre-existing test failures fixed (cycle 222)
  - 3 real Redis bugs fixed
  - 2 coverage test cycles
  - 1 dead code removal
  - 1 gRPC Cython analysis
  - 1 gRPC Option C implementation (this cycle)
  - 5 functional test cycles
- **NEW-3 + 1 remaining gRPC test** still deferred
- **Recommended next cycle 235**: investigate test_method_dict_attr_works_daudit_19801 (different root cause)
