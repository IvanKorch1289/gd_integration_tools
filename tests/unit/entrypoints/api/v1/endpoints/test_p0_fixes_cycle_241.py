"""P0 fixes integration tests — cycle 241.

P0-1: MOCK action handler → fail-closed (503, не silent 200).
P0-2: Legacy URL aliases — `/api/v1/orders/all/` → `/api/v1/auto/orders.list`.
P0-5: Lakera fail-closed test re-enabled (старый skip удалён).

Эти тесты НЕ требуют live backend — проверяют in-process через TestClient.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_actions import (
    ActionInvokeRequest,
    invoke_action,
    router as admin_router,
)
from src.backend.entrypoints.api.generator.legacy_aliases import (
    register_legacy_aliases,
)


# ──────────────────────────────────────────────────────────────────
# P0-1: MOCK action handler → fail-closed
# ──────────────────────────────────────────────────────────────────


def _stub_admin_marketplace_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub feature_flags.admin_marketplace_endpoints = True для тестов invoke."""

    class _Flags:
        admin_marketplace_endpoints = True

    # Patch the lazy import in admin_actions
    import src.backend.entrypoints.api.v1.endpoints.admin_actions as admin_actions_mod
    monkeypatch.setattr(
        admin_actions_mod, "_check_flag_enabled", lambda: None,
    )


@pytest.mark.asyncio
async def test_p0_1_invoke_action_registry_none_raises_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При registry=None — HTTP 503, не silent 200 + mock."""
    _stub_admin_marketplace_enabled(monkeypatch)
    body = ActionInvokeRequest(name="orders.get", payload={"limit": 1})

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.admin_actions._get_registry",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await invoke_action(body)

    assert exc_info.value.status_code == 503
    assert "ActionHandlerRegistry недоступен" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_p0_1_invoke_action_registry_none_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При registry=None — emit warning log для observability."""
    _stub_admin_marketplace_enabled(monkeypatch)
    body = ActionInvokeRequest(name="orders.get", payload={"limit": 1})

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.admin_actions._get_registry",
        return_value=None,
    ):
        with patch(
            "src.backend.entrypoints.api.v1.endpoints.admin_actions.logger"
        ) as mock_logger:
            with pytest.raises(HTTPException):
                await invoke_action(body)
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "registry_unavailable" in call_args[0][0]


# ──────────────────────────────────────────────────────────────────
# P0-2: Legacy URL aliases
# ──────────────────────────────────────────────────────────────────


def _build_test_app_with_aliases() -> FastAPI:
    """Создать test app с legacy aliases."""
    app = FastAPI()
    app.include_router(admin_router)
    register_legacy_aliases(app)
    return app


def _iter_all_routes(app: FastAPI):
    """Рекурсивно обойти все routes (включая _IncludedRouter → original_router)."""
    def _walk(routes):
        for route in routes:
            # _IncludedRouter хранит оригинальный router в .original_router
            if hasattr(route, "original_router"):
                yield from _walk(route.original_router.routes)
            elif hasattr(route, "routes") and isinstance(getattr(route, "routes", None), list):
                yield from _walk(route.routes)
            else:
                yield route
    yield from _walk(app.router.routes)


def test_p0_2_legacy_aliases_registered_count() -> None:
    """16 legacy URL алиасов зарегистрировано (4 resources × 4 verbs)."""
    app = _build_test_app_with_aliases()
    legacy_paths = []
    for route in _iter_all_routes(app):
        path = getattr(route, "path", "")
        name = getattr(route, "name", "") or ""
        if name.startswith("legacy."):
            legacy_paths.append(path)
    assert len(legacy_paths) == 16, f"Expected 16 legacy routes, got {len(legacy_paths)}: {legacy_paths}"


def test_p0_2_orders_all_returns_dispatch_call() -> None:
    """GET /api/v1/orders/all/ → orders.get dispatch call."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)

    mock_reg = MagicMock()
    mock_reg.dispatch = AsyncMock(return_value={"items": [], "total": 0})

    # Patch source location (lazy import in _dispatch).
    with patch(
        "src.backend.dsl.commands.action_registry.action_handler_registry",
        mock_reg,
    ):
        r = client.get("/api/v1/orders/all/")

    assert r.status_code == 200
    assert r.json()["action"] == "orders.get"
    mock_reg.dispatch.assert_awaited_once()
    call_args = mock_reg.dispatch.call_args[0][0]
    assert call_args.action == "orders.get"


def test_p0_2_orders_create_passes_body_as_payload() -> None:
    """POST /api/v1/orders/create/ → orders.add dispatch с body как payload."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)

    mock_reg = MagicMock()
    mock_reg.dispatch = AsyncMock(return_value={"id": 1, "created": True})

    with patch(
        "src.backend.dsl.commands.action_registry.action_handler_registry",
        mock_reg,
    ):
        r = client.post(
            "/api/v1/orders/create/",
            json={"pledge_cadastral_number": "77:01:0001:123"},
        )

    assert r.status_code == 200
    call_args = mock_reg.dispatch.call_args[0][0]
    assert call_args.action == "orders.add"
    assert call_args.payload.get("pledge_cadastral_number") == "77:01:0001:123"


def test_p0_2_orders_update_includes_id_in_path() -> None:
    """PUT /api/v1/orders/update/<id> → orders.update dispatch с id в payload."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)

    mock_reg = MagicMock()
    mock_reg.dispatch = AsyncMock(return_value={"updated": True})

    with patch(
        "src.backend.dsl.commands.action_registry.action_handler_registry",
        mock_reg,
    ):
        r = client.put("/api/v1/orders/update/42", json={"is_active": True})

    assert r.status_code == 200
    call_args = mock_reg.dispatch.call_args[0][0]
    assert call_args.action == "orders.update"
    assert call_args.payload.get("id") == 42


def test_p0_2_orders_delete_includes_id() -> None:
    """DELETE /api/v1/orders/delete/<id> → orders.delete dispatch."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)

    mock_reg = MagicMock()
    mock_reg.dispatch = AsyncMock(return_value={"deleted": True})

    with patch(
        "src.backend.dsl.commands.action_registry.action_handler_registry",
        mock_reg,
    ):
        r = client.delete("/api/v1/orders/delete/42")

    assert r.status_code == 200
    call_args = mock_reg.dispatch.call_args[0][0]
    assert call_args.action == "orders.delete"
    assert call_args.payload.get("id") == 42


def test_p0_2_unknown_resource_returns_404() -> None:
    """Unknown resource.verb → 404."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)
    r = client.get("/api/v1/unknown_resource/all/")
    assert r.status_code == 404


def test_p0_2_action_not_in_registry_returns_404() -> None:
    """Action not in registry → 404 (KeyError → JSONResponse 404)."""
    app = _build_test_app_with_aliases()
    client = TestClient(app)

    mock_reg = MagicMock()
    mock_reg.dispatch = AsyncMock(side_effect=KeyError("orders.get"))

    with patch(
        "src.backend.dsl.commands.action_registry.action_handler_registry",
        mock_reg,
    ):
        r = client.get("/api/v1/orders/all/")

    assert r.status_code == 404
    assert "не найден" in r.json()["detail"]
