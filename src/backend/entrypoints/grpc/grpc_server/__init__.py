"""gRPC server package (S65 W3 decomp from grpc_server.py 480 LOC).

3 servicers + 1 interceptor + 3 funcs → 5 files (per-concern):
- ``base.py``: BaseGRPCServicer (abstract base)
- ``order.py``: OrderGRPCServicer
- ``invoker.py``: InvokerGRPCServicer
- ``interceptor.py``: AuthInterceptor
- ``server.py``: 3 top-level server funcs

Backward-compat: ``from src.backend.entrypoints.grpc.grpc_server import OrderGRPCServicer`` works.
"""

from __future__ import annotations as annotations

from src.backend.entrypoints.grpc.grpc_server._safe_error import (
    _safe_error,  # S65 W3: top-level func re-export
)
from src.backend.entrypoints.grpc.grpc_server.base import (
    BaseGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.interceptor import (
    AuthInterceptor,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.invoker import (
    InvokerGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.order import (
    OrderGRPCServicer,  # S65 W3: re-export
)
from src.backend.entrypoints.grpc.grpc_server.server import (
    _load_tls_credentials,  # S65 W3: top-level func re-export
    serve,  # S65 W3: top-level func re-export
)

# D-AUDIT-18301 fix (cycle 183): gRPC v1.66+ checks
# `method.request_streaming` attribute when registering servicers.
# Our servicer methods are async (coroutines), not callable with
# that attribute → server fails with
# "'function' object has no attribute 'request_streaming'"
# when handling Invoke/Read/Write/etc.
#
# Fix: patch RPC methods на PARENT classes (InvokerServiceServicer и др.
# сгенерированные grpc-tools). Subclass переопределяет методы,
# но gRPC.register смотрит на parent → patch parent.
def _patch_rpc_methods() -> None:
    """Patch servicer methods с gRPC v1.66+ streaming metadata.

    Patches BOTH subclass (InvokerGRPCServicer.Invoke) AND parent
    class (InvokerServiceServicer.Invoke). Также patches auto-generated
    Stub (InvokerServiceStub.Invoke) — channel.unary_unary возвращает
    callable, gRPC проверяет request_streaming на stub method тоже.
    """
    from src.backend.entrypoints.grpc.protobuf import (
        invoker_pb2_grpc,
        orders_pb2_grpc,
        files_pb2_grpc,
    )
    _parent_class_method_map = {
        invoker_pb2_grpc.InvokerServiceServicer: ("Invoke",),
        invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
        files_pb2_grpc.FileServiceServicer: ("Read", "Write", "Open"),
        files_pb2_grpc.FileServiceStub: ("Read", "Write", "Open"),
    }
    for _parent_cls, _method_names in _parent_class_method_map.items():
        for _method_name in _method_names:
            _method = getattr(_parent_cls, _method_name, None)
            if _method is None or not callable(_method):
                continue
            if not hasattr(_method, "request_streaming"):
                _method.request_streaming = False  # type: ignore[attr-defined]
            if not hasattr(_method, "response_streaming"):
                _method.response_streaming = False  # type: ignore[attr-defined]

    # D-AUDIT-18801 fix (cycle 188): wrap Stub.__init__ methods to
    # add request_streaming/response_streaming attributes to the
    # Invoke/Read/Write callables AFTER they are assigned.
    # Auto-generated Stub class sets self.Invoke = channel.unary_unary(...)
    # in __init__ — we patch these callables post-assignment.
    from src.backend.entrypoints.grpc.protobuf import (
        invoker_pb2_grpc,
        files_pb2_grpc,
    )
    _stub_method_map = {
        invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
        files_pb2_grpc.FileServiceStub: ("Read", "Write", "Open"),
    }

    def _wrap_stub_init(original_init):
        def wrapped_init(self, channel):
            original_init(self, channel)
            for method_name in _stub_method_map.get(type(self), ()):
                method = getattr(self, method_name, None)
                if method is None or not callable(method):
                    continue
                if not hasattr(method, "request_streaming"):
                    method.request_streaming = False  # type: ignore[attr-defined]
                if not hasattr(method, "response_streaming"):
                    method.response_streaming = False  # type: ignore[attr-defined]

        return wrapped_init

    for _stub_cls in _stub_method_map:
        if hasattr(_stub_cls, "__init__"):
            _orig_init = _stub_cls.__init__
            _stub_cls.__init__ = _wrap_stub_init(_orig_init)  # type: ignore[method-assign]

    # Also patch subclass methods (override, so different function objects)
    for _cls_name in ("InvokerGRPCServicer", "OrderGRPCServicer", "FileStreamGRPCServicer"):
        try:
            _cls = globals()[_cls_name]
        except KeyError:
            continue
        for _method_name in (
            "Invoke", "Execute", "Stream", "Read", "Write", "Open",
            "Create", "ReadMany", "Update", "Delete", "List",
        ):
            _method = getattr(_cls, _method_name, None)
            if _method is None or not callable(_method):
                continue
            if not hasattr(_method, "request_streaming"):
                _method.request_streaming = False  # type: ignore[attr-defined]
            if not hasattr(_method, "response_streaming"):
                _method.response_streaming = False  # type: ignore[attr-defined]


_patch_rpc_methods()

__all__ = (
    "AuthInterceptor",
    "BaseGRPCServicer",
    "InvokerGRPCServicer",
    "OrderGRPCServicer",
    "_load_tls_credentials",
    "_safe_error",
    "serve",
)
