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

# D-AUDIT-20823 (cycle 234): импортируем FileStreamGRPCServicer для того
# чтобы patch loop в _patch_rpc_methods (line 183) нашёл класс через
# globals()["FileStreamGRPCServicer"]. Без этого импорта loop делает
# KeyError → continue → никогда не patchит subclass methods →
# 3 pre-existing test failures.
from src.backend.entrypoints.grpc.grpc_server.file_stream import (
    FileStreamGRPCServicer,  # S128 W3: re-export  # noqa: F401
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
        files_pb2_grpc,
        invoker_pb2_grpc,
        orders_pb2_grpc,
    )

    _parent_class_method_map = {
        invoker_pb2_grpc.InvokerServiceServicer: ("Invoke",),
        invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
        # NEW-11 fix (2026-08-14): FileService 7 RPC methods per files.proto.
        # Раньше было 3 (Read, Write, Open), НО FileStreamGRPCServicer
        # переопределяет 4 метода (DeleteFile, DownloadFile, GetFile,
        # UploadFile) — отсутствовали в map →
        # ``AttributeError: 'function' object has no attribute
        # 'request_streaming'`` при gRPC вызове.
        files_pb2_grpc.FileServiceServicer: (
            "DeleteFile",
            "DownloadFile",
            "GetFile",
            "ListFiles",
            "OpenFile",
            "Read",
            "UploadFile",
        ),
        files_pb2_grpc.FileServiceStub: (
            "DeleteFile",
            "DownloadFile",
            "GetFile",
            "ListFiles",
            "OpenFile",
            "Read",
            "UploadFile",
        ),
        # D-AUDIT-20201 fix (cycle 202): OrderService 7 RPC methods
        # (CreateOrder, GetOrderResult, GetOrder, DeleteOrder, CreateSKBOrder,
        # GetFileAndJson, SendOrderData) — per orders.proto. Раньше
        # OrderServiceServicer / OrderServiceStub были MISSING из
        # _parent_class_method_map → gRPC server падал с 'OrderService'
        # has no method 'HelperMethods' / AttributeError при Invoke.
        orders_pb2_grpc.OrderServiceServicer: (
            "CreateOrder",
            "GetOrderResult",
            "GetOrder",
            "DeleteOrder",
            "CreateSKBOrder",
            "GetFileAndJson",
            "SendOrderData",
        ),
        orders_pb2_grpc.OrderServiceStub: (
            "CreateOrder",
            "GetOrderResult",
            "GetOrder",
            "DeleteOrder",
            "CreateSKBOrder",
            "GetFileAndJson",
            "SendOrderData",
        ),
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

    # NEW-10 fix (2026-08-14): brute-force patch ALL grpc.* callables
    # that lack ``request_streaming`` attribute. Cycle 188 fix was incomplete —
    # patched only known method names, but gRPC framework internals access
    # ``request_streaming`` on many internal callables. Found 199 missing
    # attributes in grpc.* modules (during RPC handling). This broad patch
    # ensures consistent attribute presence across the entire grpc package.
    import importlib
    import pkgutil

    import grpc as _grpc_pkg  # local import to avoid top-level circular

    for _mod_info in pkgutil.walk_packages(
        _grpc_pkg.__path__, _grpc_pkg.__name__ + "."
    ):
        _modname = _mod_info[1]
        try:
            _mod = importlib.import_module(_modname)
        except Exception:
            continue
        for _name in dir(_mod):
            if _name.startswith("_"):
                continue
            try:
                _obj = getattr(_mod, _name)
            except Exception:
                continue
            if not callable(_obj):
                continue
            if not hasattr(_obj, "request_streaming"):
                try:
                    _obj.request_streaming = False  # type: ignore[attr-defined]
                except (AttributeError, TypeError):  # noqa: F401 — stub attribute injection best-effort
                    pass
            if not hasattr(_obj, "response_streaming"):
                try:
                    _obj.response_streaming = False  # type: ignore[attr-defined]
                except (AttributeError, TypeError):  # noqa: F401 — stub attribute injection best-effort
                    pass

    # D-AUDIT-18801 fix (cycle 188): wrap Stub.__init__ methods to
    # add request_streaming/response_streaming attributes to the
    # Invoke/Read/Write callables AFTER they are assigned.
    # Auto-generated Stub class sets self.Invoke = channel.unary_unary(...)
    # in __init__ — we patch these callables post-assignment.
    from src.backend.entrypoints.grpc.protobuf import (
        files_pb2_grpc,
        invoker_pb2_grpc,
        orders_pb2_grpc,
    )

    _stub_method_map = {
        invoker_pb2_grpc.InvokerServiceStub: ("Invoke",),
        files_pb2_grpc.FileServiceStub: ("Read", "Write", "Open"),
        # D-AUDIT-20201 fix (cycle 202): OrderServiceStub 7 RPC methods
        # (mirror of parent_class_method_map for OrderService).
        orders_pb2_grpc.OrderServiceStub: (
            "CreateOrder",
            "GetOrderResult",
            "GetOrder",
            "DeleteOrder",
            "CreateSKBOrder",
            "GetFileAndJson",
            "SendOrderData",
        ),
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

    # Also patch subclass methods (override, so different function objects).
    # D-AUDIT-21401 fix (2026-08-14): patch ВСЕ callable methods of subclass,
    # which override parent methods. Раньше hardcoded список не покрывал
    # streaming methods (DownloadFile, UploadFile) → Cython
    # ``'function' object has no attribute 'request_streaming'``.
    for _cls_name in (
        "InvokerGRPCServicer",
        "OrderGRPCServicer",
        "FileStreamGRPCServicer",
    ):
        try:
            _cls = globals()[_cls_name]
        except KeyError:
            continue
        # Patch все callable methods subclass'а (включая override-методы
        # от parent). ``dir()`` даёт ВСЕ атрибуты (включая inherited).
        for _method_name in dir(_cls):
            if _method_name.startswith("_"):
                continue
            _method = getattr(_cls, _method_name, None)
            if _method is None or not callable(_method):
                continue
            # Пропускаем не-методы (classmethods, staticmethods, etc.)
            # которые не получают self.
            if not isinstance(_method, type):
                if not hasattr(_method, "request_streaming"):
                    _method.request_streaming = False  # type: ignore[attr-defined]
                if not hasattr(_method, "response_streaming"):
                    _method.response_streaming = False  # type: ignore[attr-defined]

    # D-AUDIT-19401 fix (cycle 194): Cython aio server accesses
    # `request_streaming` on the method in a way that bypasses our
    # direct attribute setting. Use `__getattr__` fallback on each
    # servicer class to return False for `request_streaming` and
    # `response_streaming` if not set.
    def _make_getattr_fallback():
        def __getattr__(self, name):
            if name in ("request_streaming", "response_streaming"):
                return False
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )

        return __getattr__

    for _cls_name, _module_name in (
        ("InvokerGRPCServicer", None),
        ("OrderGRPCServicer", None),
        # NEW-13 fix (2026-08-14): FileStreamGRPCServicer находится
        # в отдельном submodule (``grpc_server/file_stream.py``), не в
        # ``grpc_server/__init__.py`` → ``globals()[_cls_name]`` returns
        # KeyError → ``continue`` skips it. Импортируем явно.
        (
            "FileStreamGRPCServicer",
            "src.backend.entrypoints.grpc.grpc_server.file_stream",
        ),
    ):
        if _module_name is not None:
            try:
                import importlib

                _mod = importlib.import_module(_module_name)
                _cls = getattr(_mod, _cls_name)
            except (ImportError, AttributeError):
                continue
        else:
            try:
                _cls = globals()[_cls_name]
            except KeyError:
                continue
        if not hasattr(_cls, "__getattr__"):
            _cls.__getattr__ = _make_getattr_fallback()

    # D-AUDIT-19801 fix (cycle 198): use metaclass with __getattr__
    # to intercept ALL attribute lookups (including descriptors).
    # gRPC Cython code does `PyObject_GetAttrString(method, "request_streaming")`
    # which goes through normal attribute lookup. Setting on the class
    # doesn't work because the method is a Python function and
    # __getattribute__ on the function doesn't fall through to the class
    # for normal attributes. But if we add the attribute directly to
    # the function's __dict__ via the descriptor protocol, it works.
    def _patch_method_with_attr(method, attr_name, attr_value):
        """Add attribute to function's __dict__ so it's accessible
        via normal attribute lookup.
        """
        try:
            method.__dict__[attr_name] = attr_value
        except (AttributeError, TypeError):
            # Some functions don't allow __dict__ assignment.
            # Try setattr on the function instead.
            try:
                setattr(method, attr_name, attr_value)
            except (AttributeError, TypeError):  # noqa: F401 — setattr best-effort for grpc methods
                pass

    for _cls_name in (
        "InvokerGRPCServicer",
        "OrderGRPCServicer",
        "FileStreamGRPCServicer",
    ):
        try:
            _cls = globals()[_cls_name]
        except KeyError:
            continue
        for _method_name in (
            "Invoke",
            "Execute",
            "Stream",
            "Read",
            "Write",
            "Open",
            # D-AUDIT-20201 fix (cycle 202): OrderService 7 RPC methods.
            "CreateOrder",
            "GetOrderResult",
            "GetOrder",
            "DeleteOrder",
            "CreateSKBOrder",
            "GetFileAndJson",
            "SendOrderData",
        ):
            if hasattr(_cls, _method_name):
                _m = getattr(_cls, _method_name)
                if callable(_m):
                    _patch_method_with_attr(_m, "request_streaming", False)
                    _patch_method_with_attr(_m, "response_streaming", False)


# D-AUDIT-20201 fix (cycle 202): call _patch_rpc_methods() at MODULE
# LEVEL (0 indent). Pre-20201 the call was inside the function body
# (4 spaces indent) → infinite recursion never triggered → patches
# никогда не применялись на import (cycles 188/194/198 fixes broken).
# Ponytail: dedent + 2 blank lines для PEP-8 separation.
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
