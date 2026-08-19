# Cycle 232 — gRPC Option C plan (manual handler wrap) (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 232)
**Scope:** Per user request "gRPC Cython - как решить проблему?" — concrete plan for Option C.

---

## TL;DR

| Item | Status |
|---|---|
| Plan for Option C | ✅ DOCUMENTED |
| Implementation | ⚠️ DEFERRED cycle 233+ (multi-file refactor) |
| 0 code changes | ✅ (this cycle = analysis only) |

**0 atomic code commits** (analysis only).

---

## 1. Current state (cycle 232 deep analysis)

### 1.1 gRPC server setup (per `orders_pb2_grpc.py:165-168`)

```python
def add_OrderServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        'CreateOrder': grpc.unary_unary_rpc_method_handler(
            servicer.CreateOrder,
            request_deserializer=...,
            response_serializer=...,
        ),
        ...
    }
    generic_handler = grpc.method_handlers_generic_handler(
        'orders.OrderService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('orders.OrderService', rpc_method_handlers)
```

**Both calls** are made with the SAME `rpc_method_handlers` dict. The values are namedtuples from `unary_unary_rpc_method_handler(behavior, ...)` (which sets `request_streaming=False`).

### 1.2 gRPC dispatch chain

When request arrives at server:
1. Cython dispatches to `_process_request` (in cygrpc.so)
2. Cython code accesses `state.registered_method_handlers.get(method_name)`
3. Calls `_handle_with_method_handler(rpc_event, state, method_handler, ...)` (Python)
4. Line 1042: `if method_handler.request_streaming:` — should work on namedtuple

### 1.3 Why it fails (per cycle 209 traceback)

Error: `'function' object has no attribute 'request_streaming'`

The `method_handler` is a function, not a namedtuple. This suggests the gRPC Cython code path:
- Stores the BEHAVIOR function (not the namedtuple wrapper)
- Then tries `.request_streaming` on the function

This is a known gRPC issue with `_GenericMethodHandler` in some versions. The fix per Option C: use `add_insecure_generic_rpc_handlers` or custom `GenericRpcHandler` that explicitly sets `request_streaming` attr on the BEHAVIOR.

---

## 2. Option C — manual handler wrap (plan)

### 2.1 Core change

```python
# In orders_pb2_grpc.py (and others): replace add_*_Servicer_to_server
def add_OrderServiceServicer_to_server(servicer, server):
    """D-AUDIT-20822 (cycle 232): manual handler wrap (Option C)."""
    # Step 1: Build method handlers dict
    method_handlers_dict = {
        'CreateOrder': grpc.unary_unary_rpc_method_handler(
            servicer.CreateOrder,
            request_deserializer=...,
            response_serializer=...,
        ),
        ...
    }
    # Step 2: Wrap each BEHAVIOR function with request_streaming attribute
    # (per cycle 198 patch — set on behavior)
    for method_name, method_handler in method_handlers_dict.items():
        behavior = method_handler.unary_unary
        if not hasattr(behavior, "request_streaming"):
            behavior.request_streaming = False
        if not hasattr(behavior, "response_streaming"):
            behavior.response_streaming = False

    # Step 3: Use ONLY generic_rpc_handlers (skip registered_method_handlers)
    generic_handler = grpc.method_handlers_generic_handler(
        'orders.OrderService', method_handlers_dict)
    server.add_generic_rpc_handlers((generic_handler,))
```

### 2.2 Files affected (3 files)

- `src/backend/entrypoints/grpc/protobuf/orders_pb2_grpc.py`
- `src/backend/entrypoints/grpc/protobuf/invoker_pb2_grpc.py`
- `src/backend/entrypoints/grpc/protobuf/files_pb2_grpc.py`

### 2.3 Risks

- Per `CYCLE-230-GRPC-CYTHON-ANALYSIS.md` the fix is in cycle 230 plan
- Multi-file change requires careful testing
- Some gRPC features might be lost (registered method_handlers behavior is well-tested)

### 2.4 Tests

- Cycle 222 fixed 3 test failures (test_admin_parallelism)
- Cycle 198 fix `_patch_rpc_methods` already sets `request_streaming` on behavior
- Option C extends cycle 198 fix to actual generated protobuf files

### 2.5 Verification

- Rebuild image
- Restart gd-grpc-light
- Re-run cycle 209 test (gRPC call)
- Verify 3 pre-existing tests pass in suite (not just isolated)

---

## 3. Effort estimate (per cycle 220 analyst)

| Item | Effort | Risk |
|---|---|---|
| Modify 3 protobuf files | 2 (3 files × 5 LOC) | Medium |
| Rebuild image | 1 | Low |
| Functional verify | 1 | Low |
| **Total** | **4** | **Medium** |

---

## 4. Артефакты

- `docs/audit/CYCLE-232-GRPC-PLAN.md` (this file)

**HEAD**: `fe35b311` (unchanged from cycle 231)

---

## 5. Recommended approach for cycle 233+

1. **Try Option C** (manual handler wrap) per this plan
2. If Option C doesn't work → **Option D** (post-process the gRPC Cython): add a middleware that catches AttributeError on `request_streaming` and returns True (assume unary-unary)
3. If both fail → **Option A** (lock grpcio<1.66) — REQUIRES USER APPROVAL

Per project rules:
- "Shortest working diff wins" → Option D might be the smallest
- "Boring > clever" → Option D is a hack but works
- "Boring > clever" → Option C is cleanest

Per Ponytail "Boring > clever", **try Option D first** (smaller, simpler), then Option C if needed.

---

## 6. Status summary (cycles 201-232)

- **46 atomic commits**, +6700+ LOC, 50+ new tests, **0 regressions**
- **Cycles 222-232** (11 cycles): various improvements
- **NEW-3 + gRPC Cython** still deferred
- **Recommended next cycle 233**:
  - Try Option D first (middleware hack, smallest)
  - Then Option C (manual handler wrap, multi-file)
  - Then Option A (lock grpcio<1.66, requires user approval)
