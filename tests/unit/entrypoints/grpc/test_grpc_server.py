# ruff: noqa: S101
"""Smoke tests for gRPC server (entrypoints/grpc/grpc_server.py).

The gRPC server module imports ``invoker_pb2`` at module load time which
requires generated protobuf stubs. We work around that by stubbing the
protobuf modules in sys.modules before importing the target.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

# ── Module-level stub setup ─────────────────────────────────────────


def _install_protobuf_stubs() -> None:
    """Install fake protobuf modules so grpc_server imports cleanly."""
    for name in (
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2",
        "src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2",
        "src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc",
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.InvokeResponse = MagicMock()
            mod.InvokerServiceServicer = type("Stub", (), {})
            mod.add_InvokerServiceServicer_to_server = MagicMock()
            mod.DeleteResponse = MagicMock()
            mod.OrderDetailResponse = MagicMock()
            mod.OrderResponse = MagicMock()
            mod.OrderServiceServicer = type("Stub", (), {})
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
