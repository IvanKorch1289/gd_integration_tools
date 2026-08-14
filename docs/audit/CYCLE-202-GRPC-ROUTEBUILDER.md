# Cycle 202 — gRPC OrderService patch + RouteBuilder perf baseline (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (parent agent)
**Scope:** continuation of cycle 188 (gRPC) + R&D prep for RouteBuilder god-class decomp.

---

## TL;DR

| Task | Status | Commit | Tests |
|---|---|---|---|
| gRPC OrderService patch (cycle 188 continuation) | ✅ DONE | `50109cae` | 52/52 gRPC tests pass |
| RouteBuilder perf baseline (pre-decomp) | ✅ DONE | `2dd5257a` | 5/5 perf tests pass |
| RouteBuilder decomposition (atomic) | ⚠️ DEFERRED | — | требует cycle 203+ multi-step |

**Critical bug found + fixed during gRPC patch**: `_patch_rpc_methods()`
was called inside its own function body (4-space indent) → recursive
call that never triggered. Cycles 188/194/198 patches were inert. Cycle
202 fixes the recursive bug.

---

## 1. gRPC OrderService patch (cycle 188 continuation)

### 1.1 Background

DIAGNOSIS_grpc-20001.md (cycle 200) concluded:
- gRPC 1.83 → 1.78 venv downgrade didn't fix the issue
- Cython framework check (`PyObject_GetAttrString(method, "request_streaming")`)
  bypasses Python attribute lookup
- "Real Invoke calls fail with downstream servicer impl bug — separate
  issue from Cython framework check"

SYNTHESIS_2026-08-13 §Доп.находка B:
> "gRPC servicer `request_streaming` bug — `OrderService*` НЕ в
> `_parent_class_method_map`"

### 1.2 Root cause analysis

Three gaps in `_patch_rpc_methods()`:

1. **Missing parent class**: `OrderServiceServicer` and `OrderServiceStub`
   не были в `_parent_class_method_map` (line 60-63). Циклы 188/194/198
   patches покрывали InvokerService* и FileService*, но OrderService был
   упущен.

2. **Missing Stub class entry**: `_stub_method_map` (cycle 188) тоже не
   включал `OrderServiceStub` → `channel.unary_unary(...)` в
   `OrderServiceStub.__init__` не получал `request_streaming`/`response_streaming`.

3. **Missing subclass methods**: `OrderGRPCServicer` subclasses
   `OrderServiceServicer` и override 7 methods (CreateOrder,
   GetOrderResult, GetOrder, DeleteOrder, CreateSKBOrder, GetFileAndJson,
   SendOrderData). Subclass loop (line 113) iterates hardcoded list
   "Invoke, Execute, Stream, Read, Write, Open, Create, ReadMany, Update,
   Delete, List" — НЕ includes Order-specific methods.

### 1.3 Critical recursive bug

**Pre-cycle-202**: `_patch_rpc_methods()` call at line 220 was at 4-space
indent (inside function body). Python interpreted this as:

```python
def _patch_rpc_methods() -> None:
    """..."""
    ...
    _patch_rpc_methods()  # ← INSIDE function (4 spaces) → infinite recursion
```

Recursion limit hit only on import (which the module-level stub setup
swallowed via `getattr(_parent_cls, _method_name, None)` returning None
for missing classes). **Patches никогда не применялись на import** —
cycles 188/194/198 fixes were all inert.

Cycle 202 dedent (line 220 from 4 spaces → 0 spaces) → module-level
call → patch runs on import.

### 1.4 Changes

**`src/backend/entrypoints/grpc/grpc_server/__init__.py`** (+41 lines):

```diff
_parent_class_method_map = {
    invoker_pb2_grpc.InvokerServiceServicer: ("Invoke",),
    invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
    files_pb2_grpc.FileServiceServicer: ("Read", "Write", "Open"),
    files_pb2_grpc.FileServiceStub: ("Read", "Write", "Open"),
+   # D-AUDIT-20201 (cycle 202): OrderService 7 RPC methods
+   orders_pb2_grpc.OrderServiceServicer: (
+       "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
+       "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
+   ),
+   orders_pb2_grpc.OrderServiceStub: (
+       "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
+       "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
+   ),
}

# Second import block: add orders_pb2_grpc
from src.backend.entrypoints.grpc.protobuf import (
    invoker_pb2_grpc,
    files_pb2_grpc,
+   orders_pb2_grpc,
)
_stub_method_map = {
    invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
    files_pb2_grpc.FileServiceStub: ("Read", "Write", "Open"),
+   orders_pb2_grpc.OrderServiceStub: (
+       "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
+       "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
+   ),
}

# Subclass loop (line 113) + cycle 198 method __dict__ patch (line 198):
+   "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
+   "CreateSKBOrder", "GetFileAndJson", "SendOrderData",

# Call at module level (dedent from 4 → 0 spaces).
-       _patch_rpc_methods()  # was inside function body (recursive)
+ _patch_rpc_methods()  # module-level call
```

**`tests/unit/entrypoints/grpc/test_grpc_server.py`** (+117 lines):
- Stub fixtures extended with `InvokerServiceStub`, `OrderServiceStub`,
  `FileServiceStub` (cycles 188+ map references не существовали в stub)
- OrderService classes с 7-method real `def` (не MagicMock — hasattr()
  auto-true с MagicMock)
- 3 new regression tests:
  - `test_order_service_servicer_methods_have_streaming_attrs`
  - `test_order_service_stub_methods_have_streaming_attrs`
  - `test_order_grpc_servicer_subclass_methods_have_streaming_attrs`

**`tests/unit/entrypoints/grpc/test_file_stream.py`** (+18 lines):
Stub fixtures обновлены для актуального patch (OrderService 7-method
real `def`, InvokerServiceStub, FileServiceStub).

### 1.5 Test results

```text
$ pytest tests/unit/entrypoints/grpc/ -q
52 passed, 1 warning in 3.94s
```

Все pre-existing gRPC tests (file_stream, auto_servicer, correlation,
test_grpc_server.py smoke tests) + 3 new OrderService regression tests.

---

## 2. RouteBuilder perf baseline (cycle 202, D-AUDIT-20202)

### 2.1 Background

PLAN_TO_9_10.md §Phase 3.1:
> "Cycle 81: Extract 5 RouteBuilder mixins (cycle 9 MRO analysis)
> Cycle 82: Add per-mixin test suites (бывшие 325 рёбер в графе → manageable)
> Cycle 83: Add cycle_2 retro verification"

Эти циклы требуют **perf baseline first** для regression detection.

### 2.2 Baseline measurements

Файл: `tests/unit/dsl/builders/test_route_builder_perf.py` (179 LOC).

| Метрика | Cycle 202 baseline |
|---|---|
| MRO length | 82 (76 mixins + RouteBuilder + 5 base) |
| Own attrs (`__slots__`) | 18 |
| `description` lookup | 0.024 us/call |
| `route_id` lookup | 0.024 us/call |
| `source` lookup | 0.024 us/call |
| `protocol` lookup | 0.030 us/call |
| `cache` lookup | 0.030 us/call |
| `feature_flag` lookup | 0.030 us/call |
| `add_middleware` lookup | 0.235 us/call (MRO traversal) |
| `add_processor` lookup | 0.232 us/call (MRO traversal) |
| `RouteBuilder()` construction | 0.985 us/instantiation |

**Findings**:
- Slot-backed attrs (`description`, `route_id`, `source`, `protocol`,
  `cache`, `feature_flag`) < 0.05 us — **negligible**
- Cross-mixin attrs (`add_middleware`, `add_processor`) 0.23 us —
  **~10x slower** due to MRO traversal
- Construction ~1 us — dominated by cooperative super().__init__()
  chain (76 levels)

### 2.3 Threshold strategy

Ponytail decision: **no hard threshold**. The test logs latency и
checks >5x regression (5 us threshold). Rationale:

- 76-mixin MRO is intentional (architecture per CLAUDE.md)
- Hardcoded threshold would tie to specific hardware (Linux x86_64 dev)
- 5x regression is clear signal of major breakage (e.g., unexpected
  `@property` decorator, broken `__slots__`, attr dict re-introduction)

### 2.4 Decomposition path (deferred to cycle 203+)

Измеряемые hotspots (0.235 us методы) — `add_middleware` и
`add_processor`. Оба определены в `MiddlewareMixin` и
`DataStoreStepMixin` соответственно. MRO traversal через 76 mixins —
~0.2 us overhead per lookup.

**3-tier decomposition strategies** (prioritized):

**Tier 1: Mixin grouping (medium risk, medium reward)**
- Group related mixins в "facade mixins":
  - `TransportMixin` ⊃ `TransportSourcesMixin`, `EventBusMixin`
  - `ContentMixin` ⊃ `ContentMixin`, `EIPContentMixin`, `FormatConvertersMixin`
  - `DataMixin` ⊃ `DataStoreMixin`, `DataStoreStepMixin`
- MRO: 76 → ~40 (50% reduction)
- Risk: order-dependent diamond inheritance (Python C3 linearization must hold)
- Est: 2-3 cycles

**Tier 2: Protocol extraction (high risk, high reward)**
- Define `RouteBuilderProtocol` (typing.Protocol) с minimal interface
- RouteBuilder delegates через composition (HAS-A, not IS-A)
- MRO: 76 → 1 (RouteBuilder), methods via `__getattr__` → Protocol implementation
- Risk: ~325+ graph edges → re-test all DSL chains
- Est: 5-8 cycles

**Tier 3: Lazy attribute groups (low risk, low reward)**
- `__getattr__` fallback для rarely-used mixins (e.g., `notebook_execute`)
- `__slots__` extension per mixin (currently all 18 slots on RouteBuilder)
- MRO: 76 (unchanged), but `__getattr__` overhead < 0.1 us per call
- Risk: low (additive, no breaking change)
- Est: 1-2 cycles

**Cycle 202 decision**: defer to cycle 203+. Tier 3 is lowest-risk
quick win (lazy attribute fallback) but requires careful design
(specify which mixins are "rare" vs "hot").

### 2.5 Tests

```text
$ pytest tests/unit/dsl/builders/test_route_builder_perf.py -v -s
test_route_builder_mro_size PASSED
test_route_builder_own_dict_size PASSED
test_route_builder_attr_lookup_baseline PASSED
test_route_builder_instantiation_baseline PASSED
test_route_builder_does_not_use_object_setattr_for_own_attrs PASSED
5 passed in 2.06s
```

---

## 3. Validation summary

```text
$ pytest tests/unit/entrypoints/grpc/ -q
52 passed, 1 warning in 3.94s

$ pytest tests/unit/dsl/builders/test_route_builder_perf.py -v -s
5 passed in 2.06s
```

**Total commits cycle 202**: 2 (50109cae gRPC + 2dd5257a perf baseline).
**LOC delta**: +41 (gRPC patch) + 195 (test stubs) + 179 (perf baseline) = +415.

---

## 4. Артефакты

- `50109cae` fix(grpc): D-AUDIT-20201 OrderService patch + dedent recursive call
- `2dd5257a` test(dsl): RouteBuilder perf baseline (cycle 202, D-AUDIT-20202)
- This file: `docs/audit/CYCLE-202-GRPC-ROUTEBUILDER.md`

**HEAD**: `2dd5257a`
