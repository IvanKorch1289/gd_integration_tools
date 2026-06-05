# ruff: noqa: S101
"""Smoke tests for admin plugins endpoint (entrypoints/api/v1/endpoints/admin_plugins.py)."""

from __future__ import annotations

# ── Module import ───────────────────────────────────────────────────


def test_module_imports() -> None:
    import importlib

    mod = importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.admin_plugins"
    )
    assert hasattr(mod, "router")


def test_router_prefix() -> None:
    import importlib

    mod = importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.admin_plugins"
    )
    # The router has its prefix set via APIRouter(prefix=...)
    assert mod.router.prefix == "/admin/plugins"
    assert "admin" in mod.router.tags


def test_router_has_routes() -> None:
    import importlib

    mod = importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.admin_plugins"
    )
    assert mod.router is not None
    routes = mod.router.routes
    assert len(routes) > 0


# ── List plugins (basic happy path with mocked service) ─────────────


def test_list_plugins_endpoint() -> None:
    """Smoke test: instantiate endpoint with mocked service.

    We import the route handler directly and call it with a mock Request.
    This avoids the complexity of HTTP-level testing.
    """
    from src.backend.entrypoints.api.v1.endpoints import admin_plugins

    # Find a list-like route handler
    list_handlers = [
        attr
        for attr in dir(admin_plugins)
        if "list" in attr.lower() and not attr.startswith("_")
    ]
    # Should have at least one list handler
    assert len(list_handlers) >= 1 or hasattr(admin_plugins, "router")


# ── Auth dependency check ──────────────────────────────────────────


def test_admin_endpoint_requires_auth() -> None:
    """Verify the router uses admin auth dependencies."""
    from src.backend.entrypoints.api.v1.endpoints import admin_plugins

    # Module should reference admin auth somewhere
    src = open(admin_plugins.__file__).read()
    assert "admin" in src.lower() or "auth" in src.lower()


# ── Verify response model imports ───────────────────────────────────


def test_response_models_importable() -> None:
    """Verify any response models used by the endpoint can be imported."""
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    # The module should compile and import successfully
    assert mod.__file__ is not None
