# ruff: noqa: S101
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


# ── Property test: _safe_error preserves BaseError.message verbatim ─────


@given(message=st.text(min_size=0, max_size=200))
@hyp_settings(
    max_examples=50,
    suppress_health_check=[
        __import__("hypothesis").HealthCheck.function_scoped_fixture
    ],
)
@pytest.mark.unit
def test_safe_error_base_error_preserves_message_property(
    grpc_server_module, message: str
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
