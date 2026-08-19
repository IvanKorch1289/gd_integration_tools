"""Regression-блокировка для cycle 194: ``__getattr__`` fallback на servicer classes.

``_patch_rpc_methods()`` (NEW-12) устанавливает ``__getattr__`` fallback
на ``InvokerGRPCServicer``/``OrderGRPCServicer``/``FileStreamGRPCServicer``
— возвращает ``False`` для ``request_streaming``/``response_streaming``
если атрибут не установлен явно. Это safety net для gRPC Cython, который
читает эти атрибуты на каждом servicer method.

Cycle 194 / D-AUDIT-19401: ``__getattr__`` срабатывает ТОЛЬКО для атрибутов,
которые не найдены через normal lookup (``hasattr``/``getattr`` возвращает
``False`` → ``__getattr__`` вызывается → возвращает ``False``).

Cycle 198 / D-AUDIT-19801: metaclass ``__getattr__`` — intercept ALL lookups.

Тесты:

1. ``__getattr__`` установлен на 3 servicer classes.
2. ``__getattr__`` возвращает ``False`` для ``request_streaming``/``response_streaming``.
3. ``__getattr__`` raises ``AttributeError`` для других атрибутов.
"""

from __future__ import annotations


def test_getattr_fallback_set_on_all_servicers() -> None:
    """``__getattr__`` defined на 3 servicer classes (cycle 194 fix)."""
    from src.backend.entrypoints.grpc.grpc_server import _patch_rpc_methods
    from src.backend.entrypoints.grpc.grpc_server.file_stream import (
        FileStreamGRPCServicer,
    )
    from src.backend.entrypoints.grpc.grpc_server.invoker import (
        InvokerGRPCServicer,
    )
    from src.backend.entrypoints.grpc.grpc_server.order import OrderGRPCServicer

    _patch_rpc_methods()

    assert hasattr(InvokerGRPCServicer, "__getattr__"), (
        "InvokerGRPCServicer missing __getattr__ fallback"
    )
    assert hasattr(OrderGRPCServicer, "__getattr__"), (
        "OrderGRPCServicer missing __getattr__ fallback"
    )
    assert hasattr(FileStreamGRPCServicer, "__getattr__"), (
        "FileStreamGRPCServicer missing __getattr__ fallback"
    )


def test_getattr_fallback_returns_false_for_streaming_attrs() -> None:
    """``__getattr__`` возвращает ``False`` для ``request_streaming``/``response_streaming``.

    Применяется когда direct attr lookup fails (cycle 194 safety net).
    """
    from src.backend.entrypoints.grpc.grpc_server import _patch_rpc_methods
    from src.backend.entrypoints.grpc.grpc_server.file_stream import (
        FileStreamGRPCServicer,
    )

    _patch_rpc_methods()

    # Создаём instance с mock attrs (без запуска gRPC)
    class _MockService(FileStreamGRPCServicer):
        pass

    instance = _MockService()
    ga = FileStreamGRPCServicer.__getattr__

    # request_streaming/response_streaming возвращают False
    assert ga(instance, "request_streaming") is False
    assert ga(instance, "response_streaming") is False


def test_getattr_fallback_raises_attributeerror_for_other_attrs() -> None:
    """``__getattr__`` raises ``AttributeError`` для других имён (нормальная Python семантика)."""
    from src.backend.entrypoints.grpc.grpc_server import _patch_rpc_methods
    from src.backend.entrypoints.grpc.grpc_server.file_stream import (
        FileStreamGRPCServicer,
    )

    _patch_rpc_methods()
    ga = FileStreamGRPCServicer.__getattr__

    class _MockService(FileStreamGRPCServicer):
        pass

    instance = _MockService()
    try:
        ga(instance, "nonexistent_attr_xyz")
        raise AssertionError("Expected AttributeError")
    except AttributeError as exc:
        assert "nonexistent_attr_xyz" in str(exc)


def test_method_dict_attr_works_daudit_19801() -> None:
    """Cycle 198 fix: ``method.__dict__[attr] = value`` (NOT metaclass).

    Альтернатива к metaclass-подходу: напрямую модифицируем ``method.__dict__``
    чтобы ``PyObject_GetAttrString(method, "request_streaming")`` находил
    attribute через descriptor protocol. Это работает для sync methods
    (DeleteFile, GetFile, OrderService methods), но НЕ для async generator
    / coroutine (DownloadFile, UploadFile) — см. NEW-12 known issues.
    """
    from src.backend.entrypoints.grpc.grpc_server import _patch_rpc_methods
    from src.backend.entrypoints.grpc.grpc_server.file_stream import (
        FileStreamGRPCServicer,
    )

    _patch_rpc_methods()

    # DeleteFile (sync) — should have request_streaming via direct set
    method = FileStreamGRPCServicer.DeleteFile
    assert hasattr(method, "request_streaming"), (
        "FileStreamGRPCServicer.DeleteFile missing request_streaming (cycle 198 fix)"
    )
    # Проверяем что attribute в __dict__ (не через metaclass __getattr__)
    assert "request_streaming" in method.__dict__, (
        "Cycle 198: request_streaming должен быть в method.__dict__"
    )
