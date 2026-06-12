"""Tests для core.auth.gateway (S95 W4 AuthGateway facade)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]


# ─────────── Gateway Module Tests ───────────


def test_gateway_module_re_exports_canonical_api() -> None:
    """core.auth.gateway экспортирует public API (AuthContext, AuthMethod, etc)."""
    from src.backend.core.auth import gateway

    # Все ключевые symbols доступны
    assert hasattr(gateway, "AuthContext")
    assert hasattr(gateway, "AuthMethod")
    assert hasattr(gateway, "verify_request")
    assert hasattr(gateway, "require_auth")
    assert hasattr(gateway, "set_default_auth")
    assert hasattr(gateway, "AuthGateway")
    # All in __all__
    for name in gateway.__all__:
        assert hasattr(gateway, name), f"{name} not in gateway module"


def test_gateway_verify_request_is_same_as_auth_selector() -> None:
    """verify_request в gateway = same function object как в auth_selector (re-export)."""
    from src.backend.core.auth import gateway
    from src.backend.entrypoints.api.dependencies import auth_selector

    assert gateway.verify_request is auth_selector.verify_request


def test_gateway_require_auth_is_same_as_auth_selector() -> None:
    """require_auth в gateway = same function object как в auth_selector."""
    from src.backend.core.auth import gateway
    from src.backend.entrypoints.api.dependencies import auth_selector

    assert gateway.require_auth is auth_selector.require_auth


def test_gateway_classes_re_exported() -> None:
    """AuthContext и AuthMethod в gateway = same class как в core.auth."""
    from src.backend.core import auth as core_auth
    from src.backend.core.auth import gateway

    assert gateway.AuthContext is core_auth.AuthContext
    assert gateway.AuthMethod is core_auth.AuthMethod


# ─────────── AuthGateway Class Tests ───────────


def test_auth_gateway_class_default_method() -> None:
    """AuthGateway(default=API_KEY) — default method = API_KEY."""
    from src.backend.core.auth import gateway

    g = gateway.AuthGateway()
    assert g._default_method == gateway.AuthMethod.API_KEY


def test_auth_gateway_class_custom_default() -> None:
    """AuthGateway(default=JWT) — custom default method."""
    from src.backend.core.auth import gateway

    g = gateway.AuthGateway(default_method=gateway.AuthMethod.JWT)
    assert g._default_method == gateway.AuthMethod.JWT


def test_auth_gateway_require_delegates() -> None:
    """gateway.require() возвращает FastAPI dependency (callable)."""
    from src.backend.core.auth import gateway

    g = gateway.AuthGateway(default_method=gateway.AuthMethod.API_KEY)
    dep = g.require()  # default
    assert callable(dep)
    # Custom methods
    dep2 = g.require(methods=gateway.AuthMethod.JWT)
    assert callable(dep2)


@pytest.mark.asyncio
async def test_auth_gateway_verify_with_mock_request() -> None:
    """AuthGateway.verify() вызывает verify_request с default methods."""
    from unittest.mock import MagicMock

    from src.backend.core.auth import gateway

    g = gateway.AuthGateway(default_method=gateway.AuthMethod.API_KEY)
    request = MagicMock()
    request.state.auth = None
    # Mock request без credentials → verify_request returns None
    result = await g.verify(request)
    assert result is None or hasattr(result, "method")


# ─────────── Policy Tests (no silent stdlib import in gateway) ───────────


def test_gateway_module_no_stdlib_logging() -> None:
    """core.auth.gateway не использует stdlib logging (только core.logging)."""
    import re

    src = (PROJECT_ROOT / "src/backend/core/auth/gateway.py").read_text()
    assert not re.search(r"^import logging$", src, re.MULTILINE)
    assert not re.search(r"^from logging import", src, re.MULTILINE)
