# Cycle 231 — gRPC Cython investigation (no fix, pre-existing) (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 231)
**Scope:** Per user request "gRPC Cython - как решить проблему?" — attempt concrete fix.

---

## TL;DR

| Item | Status |
|---|---|
| Concrete fix attempt (Ponytail-win) | ❌ REVERTED (didn't help) |
| 3 tests still fail (pre-existing) | ❌ Confirmed pre-existing |
| Real gRPC Cython fix | ❌ Defer cycle 232+ (multi-file refactor) |

**0 code commits** (cycle 231 = investigation only, all changes reverted).

---

## 1. Investigation

### 1.1 Where error comes from (cycle 230 confirmed)

`.venv/lib/python3.14/site-packages/grpc/_server.py:1042`:
```python
if method_handler.request_streaming:
```

`method_handler` should be `RpcMethodHandler` namedtuple, but error says it's a `function` (per cycle 209 traceback).

### 1.2 gRPC stub class methods

```python
# orders_pb2_grpc.py:172
class OrderService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def CreateOrder(request, target, ...):
        """Метод CreateOrder (см. signature)."""
        return grpc.experimental.unary_unary(...)
```

### 1.3 Ponytail-win attempt (D-AUDIT-20821)

Added class attributes to STUB classes:
```python
class OrderService(object):
    request_streaming = False
    response_streaming = False
```

Applied to: `OrderService`, `InvokerService`, `FileService` (3 files).

### 1.4 Why this didn't help

Test failures:
- `test_delete_file_has_request_streaming` (FileStreamGRPCServicer.DeleteFile)
- `test_get_file_has_request_streaming` (FileStreamGRPCServicer.GetFile)
- `test_method_dict_attr_works_daudit_19801`

These tests check the **SERVICER** class (where users add methods), NOT the STUB class. My fix added attributes to STUB class — wrong scope.

### 1.5 Pre-existing failures

Same 3 tests fail BEFORE my changes (verified via git stash). They are **pre-existing** and NOT caused by cycle 231.

---

## 2. Real fix options (per cycle 230 analysis)

### 2.1 Option A: Lock grpcio<1.66

- **Status**: REJECTED (per project rules: lock file change requires approval)
- **Verdict**: NOT IMPLEMENTED

### 2.2 Option B: Patch user servicer methods

- **Status**: Already tried in cycle 202, DIDN'T WORK
- Cycle 198 fix (`_patch_rpc_methods`) sets attributes on the methods, but the actual gRPC Cython code path uses a different check

### 2.3 Option C: Manual handler wrap (effort 5, high risk)

- **Status**: Recommended for cycle 232+ (multi-file refactor)
- **Code sketch**:
```python
class CustomGenericHandler(grpc.GenericRpcHandler):
    def __init__(self, servicer):
        self.servicer = servicer
    def service(self, call_details):
        return grpc.unary_unary_rpc_method_handler(
            getattr(self.servicer, call_details.method.split("/")[-1]),
            ...
        )
```

---

## 3. Validation

| Test | Result |
|---|---|
| `test_method_dict_attr_works_daudit_19801` (isolated) | ✅ PASS |
| `test_method_dict_attr_works_daudit_19801` (in suite) | ❌ FAIL (pre-existing test isolation issue) |
| `test_delete_file_has_request_streaming` (isolated) | ✅ PASS |
| `test_delete_file_has_request_streaming` (in suite) | ❌ FAIL (pre-existing) |
| `test_get_file_has_request_streaming` (isolated) | ✅ PASS |
| `test_get_file_has_request_streaming` (in suite) | ❌ FAIL (pre-existing) |

**Conclusion**: Tests pass in isolation, fail in suite. **Pre-existing test isolation issue** — not caused by cycle 231.

---

## 4. Артефакты

- `docs/audit/CYCLE-231-GRPC-INVESTIGATION.md` (this file)

**HEAD**: `6d733da3` (unchanged from cycle 230)

---

## 5. Status summary (cycles 201-231)

- **46 atomic commits**, +6700+ LOC, 50+ new tests, **0 regressions** (no new failures introduced)
- **Cycles 222-231** (10 cycles):
  - 9 pre-existing test failures fixed
  - 3 real Redis bugs fixed
  - 2 coverage test cycles
  - 1 dead code removal
  - 1 gRPC Cython analysis (cycle 230)
  - 1 gRPC fix attempt (cycle 231 — REVERTED)
  - 5 functional test cycles
- **NEW-3 + gRPC Cython** still deferred (multi-cycle work)
- **Recommended next cycles** (per analyst):
  - 232: gRPC Option C (manual handler wrap)
  - 233: NEW-3 MCP lifespan wire
  - 234: DSL builder mixin lazy `__getattr__`
  - 235: McpAuthMiddleware re-attach
  - 236: more coverage push (137 candidates)
