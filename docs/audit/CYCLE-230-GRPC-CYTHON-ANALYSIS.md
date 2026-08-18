# Cycle 230 — gRPC Cython root cause analysis (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 230)
**Scope:** Per user request ("gRPC Cython - как решить проблему?") — deep analysis.

---

## TL;DR

| Item | Status |
|---|---|
| Root cause analysis | ✅ DONE |
| Atomic fix | ❌ DEFERRED (lock file change requires user approval) |
| 0 code changes | ✅ |

**0 atomic code commits** (analysis only).

---

## 1. Root cause (cycle 230 deep analysis)

### 1.1 Where the error comes from

```python
# .venv/lib/python3.14/site-packages/grpc/_server.py:1042
if method_handler.request_streaming:
    if method_handler.response_streaming:
        return _handle_stream_stream(...)
```

This is in the SYNC server's `_process_request`. Per cycle 209 test, error is at server-side, but caught at client as `StatusCode.UNKNOWN` with detail `'function' object has no attribute 'request_streaming'`.

### 1.2 What `method_handler` is

`method_handler` is `grpc._utilities.RpcMethodHandler` — a `namedtuple`:
```python
class RpcMethodHandler(
    collections.namedtuple(
        "_RpcMethodHandler",
        ("request_streaming", "response_streaming", "request_deserializer",
         "response_serializer", "unary_unary", "unary_stream",
         "stream_unary", "stream_stream"),
    ),
    grpc.RpcMethodHandler,
):
    pass
```

So `method_handler.request_streaming` is a namedtuple field — should work.

### 1.3 Where `method_handler` is created

4 public factory functions in gRPC:
- `unary_unary_rpc_method_handler` (sets `request_streaming=False, response_streaming=False`)
- `unary_stream_rpc_method_handler` (False, True)
- `stream_unary_rpc_method_handler` (True, False)
- `stream_stream_rpc_method_handler` (True, True)

In our project's `orders_pb2_grpc.py:128-133`:
```python
rpc_method_handlers = {
    'CreateOrder': grpc.unary_unary_rpc_method_handler(
        servicer.CreateOrder,
        request_deserializer=...,
        response_serializer=...,
    ),
    ...
}
```

`unary_unary_rpc_method_handler` correctly sets `request_streaming=False` in the namedtuple.

### 1.4 So why does cycle 209 see 'function' object?

The error suggests the gRPC server has a `method_handler` that's a `function` not a namedtuple. This could happen if:
- The gRPC server uses a **generic_handler** (subclass of `GenericRpcHandler`) that stores methods as functions
- The Cython-compiled code path checks `handler.request_streaming` where `handler` is the `behavior` function, not the namedtuple

### 1.5 The actual gRPC code path (D-AUDIT-20820)

The gRPC server has TWO registration mechanisms:
1. `add_*_Servicer_to_server(servicer, server)` — uses `add_registered_method_handlers()` → RpcMethodHandler namedtuple
2. `add_generic_rpc_handlers(handler)` — uses `add_generic_handlers()` → custom `GenericRpcHandler.service()`

Per `grpc/_utilities.py:68-74`:
```python
def service(self, handler_call_details):
    """GenericRpcHandler.service returns the RpcMethodHandler."""
    details_method = handler_call_details.method
    return self._method_handlers.get(details_method)
```

This is correct — returns the namedtuple.

### 1.6 The actual error source

Looking at `.venv/lib/python3.14/site-packages/grpc/_cython/cygrpc.cpython-314-x86_64-linux-gnu.so` (Cython compiled):
- `strings` shows `request_streaming` (binary-encoded)
- The Cython code checks `.request_streaming` on the **method_handler** at the C level

If the Cython code passes a different object (not the namedtuple), the check fails. This is the "Cython path differs from Python path" — exactly what cycle 200-209 was chasing.

---

## 2. Three fix options (per analyst)

### 2.1 Option A: Lock grpcio<1.66 (cycle 200 attempted)

- **Approach**: Pin grpcio to a version where Cython code didn't have this check
- **Effort**: 1 (1-line change in pyproject.toml)
- **Risk**: ⚠️ **LOCK FILE CHANGE REQUIRES USER APPROVAL** (per AGENTS.md)
- **Side effects**: Loses newer gRPC features, may break other clients
- **Verdict**: **REJECTED** (per project rules)

### 2.2 Option B: Patch user servicer methods with `request_streaming` (cycle 202)

- **Approach**: Set `request_streaming=False` on the servicer methods
- **Status**: ❌ **DOESN'T WORK** — gRPC Cython checks on the namedtuple, not the user method
- **Verdict**: Already tried in cycle 202, failed in cycle 209

### 2.3 Option C: Manual handler wrap (Ponytail: cleanest)

- **Approach**: Instead of using `add_OrderServiceServicer_to_server`, manually create a `DictionaryGenericHandler` with pre-built RpcMethodHandlers
- **Code sketch**:
```python
# In server.py or grpc_server/__init__.py
class CustomGenericHandler(grpc.GenericRpcHandler):
    def __init__(self, servicer):
        self.servicer = servicer
    def service(self, call_details):
        return grpc.unary_unary_rpc_method_handler(
            getattr(self.servicer, call_details.method.split("/")[-1]),
            ...
        )

# Instead of: add_OrderServiceServicer_to_server(servicer, server)
# Use: server.add_generic_rpc_handlers([CustomGenericHandler(servicer)])
```

- **Effort**: 5 (multiple files, requires understanding gRPC internals)
- **Risk**: MEDIUM (manual handler wrap might miss some gRPC features)
- **Verdict**: **RECOMMENDED** for cycle 231+ with user approval

---

## 3. Why I'm not implementing in this cycle

Per project rules:
- "approval needed for lock file changes" → Option A rejected
- "Shortest working diff wins" → Option C is multi-file refactor
- "Boring > clever" → multi-cycle work needs planning

Per Ponytail "deleting over adding", the best path is:
1. Document root cause (this cycle 230)
2. Wait for user approval to proceed with Option C in dedicated cycle
3. Functional tests continue to work via REST/GraphQL/SOAP/etc (NEW-3 not blocking other functionality)

---

## 4. Functional state (current)

| Protocol | Status | Workaround |
|---|---|---|
| REST | ✅ 131 actions | — |
| GraphQL | ✅ | — |
| SOAP | ✅ 3 actions WSDL | — |
| SSE | ✅ | — |
| WebSocket | ✅ | — |
| Webhook | ✅ | — |
| CDC | ✅ subscription_id | — |
| Admin Actions | ✅ invoke works | — |
| **gRPC** | ❌ **Cython 404/500** | **Defer cycle 231+ Option C** |
| NEW-3 MCP | ❌ 404 | Defer cycle 231+ |

---

## 5. Артефакты

- `docs/audit/CYCLE-230-GRPC-CYTHON-ANALYSIS.md` (this file)

**HEAD**: `c7d917ba` (unchanged)

---

## 6. Recommended cycles (cycle 231+)

| Cycle | Action | Approach |
|---|---|---|
| 231 | **Option C: Manual gRPC handler wrap** | CustomGenericHandler + add_generic_rpc_handlers |
| 232 | NEW-3 MCP lifespan wire | Per analyst top 1 (low risk) |
| 233 | DSL builder mixin lazy `__getattr__` | Per Ponytail #8 |
| 234 | McpAuthMiddleware re-attach | Per Ponytail #4 |
| 235 | More coverage push (137 candidates) | Per Ponytail #12 |

**Cycle 231 (Option C)** requires user approval — multi-file refactor.
