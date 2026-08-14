"""Smoke tests for gRPC server (entrypoints/grpc/grpc_server.py).

The gRPC server module imports ``invoker_pb2`` at module load time which
requires generated protobuf stubs. We work around that by stubbing the
protobuf modules in sys.modules before importing the target.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

# ── Module-level stub setup ─────────────────────────────────────────


def _install_protobuf_stubs() -> None:
    """Install fake protobuf modules so grpc_server imports cleanly."""
    for name in (
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2",
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc",
        "src.backend.entrypoints.grpc.protobuf.files_pb2",
        "src.backend.entrypoints.grpc.protobuf.files_pb2_grpc",
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)

            # D-AUDIT-20201 (cycle 202): real `def` для methods
            # (MagicMock auto-creates attrs → hasattr always True).
            # Empty stub classes для Invoker/FileStream (no methods to
            # patch в test scope); OrderService classes полные.
            def _stub_method(self, request, context):  # pragma: no cover
                return None

            _order_methods = (
                "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
                "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
            )

            # PB2 messages (used by add_*_to_server imports в grpc_server).
            mod.InvokeResponse = MagicMock()
            mod.DeleteResponse = MagicMock()
            mod.OrderDetailResponse = MagicMock()
            mod.OrderResponse = MagicMock()
            mod.FileResponse = MagicMock()

            # PB2_grpc servicers + stubs.
            if "invoker" in name:
                mod.InvokerServiceServicer = type("Stub", (), {})
                mod.InvokerServiceStub = type("Stub", (), {})
            elif "files" in name:
                mod.FileServiceServicer = type("Stub", (), {})
                mod.FileServiceStub = type("Stub", (), {})
            elif "orders" in name:
                mod.OrderServiceServicer = type(
                    "OrderServiceServicer",
                    (),
                    {m: _stub_method for m in _order_methods},
                )
                mod.OrderServiceStub = type(
                    "OrderServiceStub",
                    (),
                    {m: _stub_method for m in _order_methods},
                )

            # add_*_to_server functions (callable import).
            mod.add_InvokerServiceServicer_to_server = MagicMock()
            mod.add_FileServiceServicer_to_server = MagicMock()
            mod.add_OrderServiceServicer_to_server = MagicMock()
            sys.modules[name] = mod


@pytest.fixture
def grpc_server_module():
    _install_protobuf_stubs()
    return importlib.import_module("src.backend.entrypoints.grpc.grpc_server")


# ── _safe_error: pure function tests ────────────────────────────────


def test_safe_error_with_base_error(grpc_server_module) -> None:
    from src.backend.core.errors import BaseError

    # BaseError(message=...) is keyword-only per its __init__ signature.
    exc = BaseError(message="controlled domain message")
    assert (
        grpc_server_module._safe_error(exc, "corr-123") == "controlled domain message"
    )


def test_safe_error_with_generic_exception(grpc_server_module) -> None:
    assert (
        grpc_server_module._safe_error(RuntimeError("internal stack trace"), "abc")
        == "Internal server error; ref=abc"
    )


def test_safe_error_with_value_error(grpc_server_module) -> None:
    assert (
        grpc_server_module._safe_error(ValueError("password=secret"), "xyz")
        == "Internal server error; ref=xyz"
    )


def test_safe_error_does_not_leak_traceback(grpc_server_module) -> None:
    try:
        raise RuntimeError("password=hunter2 db=prod")
    except RuntimeError as exc:
        msg = grpc_server_module._safe_error(exc, "trace-1")
    assert "hunter2" not in msg
    assert "prod" not in msg
    assert "trace-1" in msg


# ── BaseGRPCServicer init ───────────────────────────────────────────


def test_base_grpc_servicer_init(grpc_server_module) -> None:
    servicer = grpc_server_module.BaseGRPCServicer()
    assert servicer.logger is not None


# === Unit tests (Wave 41 coverage push) ===


@pytest.mark.unit
def test_serialize_pydantic_like_model_uses_model_dump(grpc_server_module) -> None:
    """Pydantic-like object (has model_dump) → JSON of model_dump(mode='json')."""
    servicer = grpc_server_module.BaseGRPCServicer()
    fake = MagicMock()
    fake.model_dump.return_value = {"id": 1, "name": "alpha"}
    result = servicer._serialize(fake)
    fake.model_dump.assert_called_once_with(mode="json")
    parsed = json.loads(result)
    assert parsed == {"id": 1, "name": "alpha"}


@pytest.mark.unit
def test_serialize_dict_returns_json(grpc_server_module) -> None:
    """Plain dict → JSON-encoded string (orjson round-trip)."""
    servicer = grpc_server_module.BaseGRPCServicer()
    result = servicer._serialize({"key": "value", "n": 42})
    assert json.loads(result) == {"key": "value", "n": 42}


@pytest.mark.unit
def test_load_tls_credentials_disabled_returns_none(grpc_server_module) -> None:
    """When tls_enabled=False on settings.grpc → return None (no TLS).

    Note (S129 W2, Rule #124): ``_load_tls_credentials`` lives в
    ``grpc_server.server`` submodule (не в package ``__init__``), и его
    name-binding ``settings`` resolves в server module namespace.
    Патчить нужно ``server.settings``, не package ``settings``.
    Package не имеет своего ``settings`` атрибута (AttributeError до fix).
    """
    from src.backend.entrypoints.grpc.grpc_server import server

    fake_settings = MagicMock()
    fake_settings.grpc.tls_enabled = False
    with patch.object(server, "settings", fake_settings):
        result = grpc_server_module._load_tls_credentials()
    assert result is None


# ── D-AUDIT-20201: OrderService RPC method patching (cycle 202) ─────


@pytest.mark.unit
def test_order_service_servicer_methods_have_streaming_attrs(
    grpc_server_module,
) -> None:
    """OrderServiceServicer 7 RPC methods (per orders.proto) receive
    request_streaming/response_streaming=False after _patch_rpc_methods().

    Cycle 188/194/198 fixes patches InvokerServiceServicer и
    FileServiceServicer, но OrderServiceServicer был MISSING →
    gRPC server падал с ``'OrderService' object has no attribute
    'HelperMethods'`` при Invoke. Cycle 202 closes the gap.
    """
    from src.backend.entrypoints.grpc.protobuf import orders_pb2_grpc

    order_methods = (
        "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
        "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
    )
    for method_name in order_methods:
        method = getattr(orders_pb2_grpc.OrderServiceServicer, method_name)
        assert method is not None, (
            f"OrderServiceServicer.{method_name} missing"
        )
        assert getattr(method, "request_streaming", "MISSING") is False, (
            f"OrderServiceServicer.{method_name}.request_streaming "
            "not patched to False"
        )
        assert getattr(method, "response_streaming", "MISSING") is False, (
            f"OrderServiceServicer.{method_name}.response_streaming "
            "not patched to False"
        )


@pytest.mark.unit
def test_order_service_stub_methods_have_streaming_attrs(
    grpc_server_module,
) -> None:
    """OrderServiceStub 7 RPC methods (per orders.proto) receive
    request_streaming/response_streaming=False after _patch_rpc_methods().

    Stub методы назначаются в ``__init__`` (после class definition),
    поэтому D-AUDIT-18801 wrap __init__ патчит их post-assignment.
    Cycle 202 добавляет OrderServiceStub в _stub_method_map.
    """
    from src.backend.entrypoints.grpc.protobuf import orders_pb2_grpc

    order_methods = (
        "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
        "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
    )
    for method_name in order_methods:
        method = getattr(orders_pb2_grpc.OrderServiceStub, method_name)
        assert method is not None, (
            f"OrderServiceStub.{method_name} missing"
        )
        assert getattr(method, "request_streaming", "MISSING") is False, (
            f"OrderServiceStub.{method_name}.request_streaming "
            "not patched to False"
        )
        assert getattr(method, "response_streaming", "MISSING") is False, (
            f"OrderServiceStub.{method_name}.response_streaming "
            "not patched to False"
        )


@pytest.mark.unit
def test_order_grpc_servicer_subclass_methods_have_streaming_attrs(
    grpc_server_module,
) -> None:
    """OrderGRPCServicer subclass overrides all 7 OrderService methods.

    Subclass methods — different function objects (override), поэтому
    D-AUDIT-18301 patch loop итерирует каждый subclass и patch
    request_streaming/response_streaming на override methods.
    """
    order_methods = (
        "CreateOrder", "GetOrderResult", "GetOrder", "DeleteOrder",
        "CreateSKBOrder", "GetFileAndJson", "SendOrderData",
    )
    subclass = grpc_server_module.OrderGRPCServicer
    for method_name in order_methods:
        method = getattr(subclass, method_name, None)
        assert method is not None, (
            f"OrderGRPCServicer.{method_name} missing"
        )
        assert getattr(method, "request_streaming", "MISSING") is False, (
            f"OrderGRPCServicer.{method_name}.request_streaming "
            "not patched to False"
        )
        assert getattr(method, "response_streaming", "MISSING") is False, (
            f"OrderGRPCServicer.{method_name}.response_streaming "
            "not patched to False"
        )


# ── Property test: _safe_error preserves BaseError.message verbatim ─────


@given(message=st.text(min_size=0, max_size=200))
@hyp_settings(
    max_examples=50,
    suppress_health_check=[
        __import__("hypothesis").HealthCheck.function_scoped_fixture,
    ],
)
@pytest.mark.unit
def test_safe_error_base_error_preserves_message_property(
    grpc_server_module, message: str,
) -> None:
    """For any string message, _safe_error returns it unchanged for BaseError.

    Invariant: BaseError instances always flow their .message attribute
    through to the gRPC client (no truncation, no formatting, no
    correlation-id prefix). Generic exceptions DO get the correlation-id
    prefix — BaseError must NOT.

    The function-scoped fixture is safe to share across hypothesis
    examples (no mutable state mutated by _safe_error).
    """
    from src.backend.core.errors import BaseError

    exc = BaseError(message=message)
    result = grpc_server_module._safe_error(exc, "ref-abc")
    assert result == message
    assert "ref-abc" not in result  # BaseError must not get the generic ref prefix
    assert "Internal server error" not in result
