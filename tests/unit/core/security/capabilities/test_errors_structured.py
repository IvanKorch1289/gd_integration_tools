"""Unit tests for structured error reporting (Sprint 36 V15 GAP).

Покрывает:
* ``to_dict()`` для :class:`CapabilityError`, :class:`CapabilityDeniedError`,
  :class:`CapabilityNotFoundError`, :class:`CapabilitySupersetError`.
* ``correlation_id`` propagation через все ошибки.
* Message format: содержит plugin/capability/scope.
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef

# ── CapabilityError (base) ────────────────────────────────────────


@pytest.mark.unit
def test_capability_error_to_dict_basic() -> None:
    """Base ``to_dict()`` содержит ``error_type``, ``message``, ``correlation_id``."""
    err = CapabilityError("some failure")
    d = err.to_dict()
    assert d["error_type"] == "CapabilityError"
    assert d["message"] == "some failure"
    assert d["correlation_id"] is None


@pytest.mark.unit
def test_capability_error_correlation_id_propagation() -> None:
    """``correlation_id`` сохраняется в ``to_dict()``."""
    err = CapabilityError("failure")
    err.correlation_id = "trace-123"
    d = err.to_dict()
    assert d["correlation_id"] == "trace-123"


# ── CapabilityDeniedError ─────────────────────────────────────────


@pytest.mark.unit
def test_capability_denied_error_to_dict_keys() -> None:
    """``to_dict()`` содержит все ключевые поля."""
    err = CapabilityDeniedError(
        plugin="plugin_x",
        capability="db.read",
        requested_scope="db:tenant_a:external",
        declared_scope="db:tenant_a:internal",
        tenant="tenant_a",
        principal="plugin_x",
        correlation_id="trace-456",
    )
    d = err.to_dict()
    assert d["error_type"] == "CapabilityDeniedError"
    assert d["capability"] == "db.read"
    assert d["tenant"] == "tenant_a"
    assert d["principal"] == "plugin_x"
    assert d["plugin"] == "plugin_x"
    assert d["scope"] == "db:tenant_a:external"
    assert d["declared_scope"] == "db:tenant_a:internal"
    assert d["correlation_id"] == "trace-456"
    assert "db.read" in d["message"]


@pytest.mark.unit
def test_capability_denied_error_default_tenant() -> None:
    """Default tenant = ``_system`` (backward compat)."""
    err = CapabilityDeniedError(
        plugin="plugin_x",
        capability="db.read",
        requested_scope=None,
        declared_scope=None,
    )
    assert err.tenant == "_system"
    assert err.principal == "plugin_x"  # default == plugin


@pytest.mark.unit
def test_capability_denied_error_message_contains_capability() -> None:
    """Message содержит plugin и capability для debugging."""
    err = CapabilityDeniedError(
        plugin="plugin_credit",
        capability="net.outbound",
        requested_scope="net:any",
        declared_scope=None,
    )
    msg = str(err)
    assert "plugin_credit" in msg
    assert "net.outbound" in msg


# ── CapabilityNotFoundError ───────────────────────────────────────


@pytest.mark.unit
def test_capability_not_found_error_to_dict() -> None:
    """``to_dict()`` содержит ``name`` как ``capability``."""
    err = CapabilityNotFoundError(name="unknown.capability", correlation_id="trace-789")
    d = err.to_dict()
    assert d["error_type"] == "CapabilityNotFoundError"
    assert d["capability"] == "unknown.capability"
    assert d["message"] == "Unknown capability: 'unknown.capability'"
    assert d["correlation_id"] == "trace-789"


@pytest.mark.unit
def test_capability_not_found_error_no_correlation() -> None:
    """``correlation_id=None`` по умолчанию."""
    err = CapabilityNotFoundError(name="x.y")
    assert err.correlation_id is None
    assert err.to_dict()["correlation_id"] is None


# ── CapabilitySupersetError ───────────────────────────────────────


@pytest.mark.unit
def test_capability_superset_error_to_dict() -> None:
    """``to_dict()`` содержит ``route`` и список ``offending`` (name+scope)."""
    offending = (
        CapabilityRef(name="db.read", scope="db:tenant_a:*"),
        CapabilityRef(name="net.outbound", scope=None),
    )
    err = CapabilitySupersetError(route="my_route", offending=offending)
    d = err.to_dict()
    assert d["error_type"] == "CapabilitySupersetError"
    assert d["route"] == "my_route"
    assert d["offending"] == [
        {"name": "db.read", "scope": "db:tenant_a:*"},
        {"name": "net.outbound", "scope": None},
    ]


@pytest.mark.unit
def test_capability_superset_error_message() -> None:
    """Message содержит route и offending capabilities."""
    err = CapabilitySupersetError(
        route="credit_pipeline",
        offending=(CapabilityRef(name="db.read", scope="db:*"),),
    )
    msg = str(err)
    assert "credit_pipeline" in msg
    assert "db.read" in msg
    assert "db:*" in msg


# ── Round-trip через JSON (для audit / SIEM) ──────────────────────


@pytest.mark.unit
def test_to_dict_is_json_serializable() -> None:
    """``to_dict()`` возвращает только JSON-совместимые типы."""
    import json

    err = CapabilityDeniedError(
        plugin="p",
        capability="db.read",
        requested_scope="db:x",
        declared_scope=None,
        tenant="t1",
        correlation_id="abc",
    )
    # Должно сериализоваться без исключений.
    serialized = json.dumps(err.to_dict())
    assert "db.read" in serialized
    assert "abc" in serialized
