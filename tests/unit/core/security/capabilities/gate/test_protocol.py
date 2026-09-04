"""Tests for core/security/capabilities/gate/_protocol.py (S99).

Protocol definition only — no executable statements, but verify it imports.
"""

from __future__ import annotations


def test_protocol_module_imports() -> None:
    """_protocol.py импортируется без ошибок."""
    from src.backend.core.security.capabilities.gate import _protocol

    assert _protocol is not None


def test_capability_gate_protocol_is_protocol() -> None:
    """_CapabilityGateProtocol — typing.Protocol."""
    from src.backend.core.security.capabilities.gate._protocol import (
        _CapabilityGateProtocol,
    )

    # Protocol classes have _is_protocol attribute or similar.
    assert hasattr(_CapabilityGateProtocol, "__abstractmethods__") or hasattr(
        _CapabilityGateProtocol, "_is_protocol"
    )


def test_protocol_has_required_attributes() -> None:
    """_CapabilityGateProtocol defines expected attributes."""
    from src.backend.core.security.capabilities.gate._protocol import (
        _CapabilityGateProtocol,
    )

    annotations = _CapabilityGateProtocol.__annotations__
    expected_attrs = (
        "_vocabulary",
        "_audit",
        "_declarations",
        "_cache",
        "_tenant_cache",
        "_lru_size",
        "_tenant_declarations",
        "_policy",
        "_lock",
    )
    for attr in expected_attrs:
        assert attr in annotations, f"missing attribute {attr}"
