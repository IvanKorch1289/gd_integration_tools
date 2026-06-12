"""S96 W1 — regression-блокировка для auth_selector relocation.

Гарантирует:

1. ``core.auth.auth_selector`` — канонический implementation
   (``verify_request``, ``require_auth``, ``set_default_auth``).
2. ``core.auth.gateway`` — re-export facade, импортирует из core (НЕ
   entrypoints) — иначе downward layer violation.
3. ``entrypoints.api.dependencies.auth_selector`` — DEPRECATED shim,
   бросает ``DeprecationWarning`` при import.
4. ``_VERIFIERS`` — private registry, доступен ТОЛЬКО из core.auth.auth_selector
   (НЕ из entrypoints shim, чтобы extensions не лезли в private).
5. AuthGateway OO class — re-exports core.auth.auth_selector.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable

import pytest


def test_core_auth_selector_has_canonical_impl() -> None:
    """``core.auth.auth_selector`` — канонический implementation."""
    from src.backend.core.auth import auth_selector as core_sel

    assert hasattr(core_sel, "verify_request")
    assert hasattr(core_sel, "require_auth")
    assert hasattr(core_sel, "set_default_auth")
    assert hasattr(core_sel, "_VERIFIERS")  # private registry lives in core
    assert callable(core_sel.verify_request)
    assert callable(core_sel.require_auth)


def test_gateway_imports_from_core_not_entrypoints() -> None:
    """``core.auth.gateway`` импортирует ``verify_request`` из core.

    Если импорт пойдёт из entrypoints — downward layer violation.
    """
    from src.backend.core.auth import auth_selector as core_sel
    from src.backend.core.auth import gateway

    # verify_request в gateway и в core — ОДИН И ТОТ ЖЕ объект.
    assert gateway.verify_request is core_sel.verify_request
    assert gateway.require_auth is core_sel.require_auth
    assert gateway.set_default_auth is core_sel.set_default_auth


def test_entrypoints_shim_is_deprecated() -> None:
    """``entrypoints.api.dependencies.auth_selector`` — DEPRECATED shim."""
    with pytest.warns(DeprecationWarning, match="S96 W1"):
        # Force reimport — cache may suppress warn after first import
        import importlib

        mod = importlib.import_module(
            "src.backend.entrypoints.api.dependencies.auth_selector"
        )
        # Reload чтобы DeprecationWarning повторился
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.reload(mod)
            deprecation_warnings = [
                w for w in caught if issubclass(w.category, DeprecationWarning)
            ]
        assert any(
            "S96 W1" in str(w.message) and "core.auth.gateway" in str(w.message)
            for w in deprecation_warnings
        ), f"Expected S96 W1 deprecation, got: {[str(w.message) for w in deprecation_warnings]}"


def test_entrypoints_shim_re_exports_core() -> None:
    """Shim re-exports из core (НЕ имеет собственной implementation)."""
    from src.backend.core.auth import auth_selector as core_sel
    from src.backend.entrypoints.api.dependencies import auth_selector as shim

    assert shim.verify_request is core_sel.verify_request
    assert shim.require_auth is core_sel.require_auth
    assert shim.set_default_auth is core_sel.set_default_auth
    assert shim.AuthMethod is core_sel.AuthMethod
    assert shim.AuthContext is core_sel.AuthContext


def test_entrypoints_shim_hides_private_verifiers() -> None:
    """Shim НЕ leak'ит private ``_VERIFIERS`` (только public API)."""
    shim = __import__(
        "src.backend.entrypoints.api.dependencies.auth_selector",
        fromlist=["_VERIFIERS"],
    )
    assert hasattr(shim, "verify_request")
    # Shim НЕ должен иметь private ``_VERIFIERS`` — extensions не должны
    # лезть в registry напрямую. Если shim имеет его — это leak.
    assert not hasattr(shim, "_VERIFIERS"), (
        "Shim must not leak _VERIFIERS — extensions must use public API"
    )


def test_auth_gateway_oo_class() -> None:
    """AuthGateway — OO class с pre-configured defaults."""
    from src.backend.core.auth.gateway import AuthGateway
    from src.backend.core.auth import AuthMethod

    gw = AuthGateway(default_method=AuthMethod.JWT)
    assert gw._default_method is AuthMethod.JWT

    gw2 = AuthGateway(default_method=[AuthMethod.API_KEY, AuthMethod.JWT])
    assert gw2._default_method == [AuthMethod.API_KEY, AuthMethod.JWT]


def test_auth_gateway_require_factory() -> None:
    """AuthGateway.require() — factory для FastAPI dependency."""
    from src.backend.core.auth.gateway import AuthGateway
    from src.backend.core.auth import AuthMethod

    gw = AuthGateway()
    dep = gw.require(methods=AuthMethod.API_KEY)
    assert callable(dep)  # FastAPI dependency factory
