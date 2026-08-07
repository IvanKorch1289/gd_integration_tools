"""D-AUDIT-07: management endpoints auth guard (CDC + Filewatcher)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.cdc import cdc_routes as cdc
from src.backend.entrypoints.filewatcher import watcher_routes as fw


def _build_app(with_admin: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(cdc.cdc_router)
    app.include_router(fw.watcher_router, prefix="/api/v1")
    if with_admin:

        async def _fake_admin() -> AuthContext:
            return AuthContext(
                method=AuthMethod.API_KEY,
                principal="test-admin",
                metadata={"admin_roles": ["super_admin"]},
            )

        app.dependency_overrides[cdc._admin_dep] = _fake_admin
        app.dependency_overrides[fw._admin_dep] = _fake_admin
    return app


def test_cdc_no_auth_rejected() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.get("/api/v1/cdc/subscriptions")
    assert resp.status_code in (401, 403)


def test_cdc_admin_ok() -> None:
    app = _build_app(with_admin=True)
    with patch(
        "src.backend.entrypoints.cdc.cdc_routes.get_cdc_client_provider"
    ) as mock_provider:
        mock_provider.return_value.list_subscriptions.return_value = []
        client = TestClient(app)
        resp = client.get("/api/v1/cdc/subscriptions")
    assert resp.status_code == 200


def test_filewatcher_no_auth_rejected() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.get("/api/v1/watchers/")
    assert resp.status_code in (401, 403)


def test_filewatcher_admin_ok() -> None:
    app = _build_app(with_admin=True)
    with patch.object(fw.watcher_manager, "list_watchers", return_value=[]):
        client = TestClient(app)
        resp = client.get("/api/v1/watchers/")
    assert resp.status_code == 200
