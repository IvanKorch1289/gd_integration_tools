"""Unit-тесты AdminAuditMiddleware (S13 K1 W2)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.admin_audit import AdminAuditMiddleware


def _make_app_with_ctx(ctx: AuthContext | None) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject(request, call_next):  # type: ignore[no-untyped-def]
        request.state.auth_context = ctx
        request.state.correlation_id = "corr-123"
        return await call_next(request)

    app.add_middleware(AdminAuditMiddleware)

    @app.patch("/tech/degradation/level")
    async def _patch_degradation(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "received": payload}

    @app.get("/tech/degradation/snapshot")
    async def _get_snapshot() -> dict[str, str]:
        return {"mode": "FULL"}

    @app.post("/api/v1/admin/resilience-profiles/foo")
    async def _put_profile(payload: dict[str, Any]) -> dict[str, Any]:
        return {"saved": True}

    @app.get("/api/v1/admin/something")
    async def _get_something() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/users")
    async def _users() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def caplog_audit(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="audit_log.admin")
    return caplog


def test_patch_admin_path_emits_audit(caplog_audit: pytest.LogCaptureFixture) -> None:
    ctx = AuthContext(
        method=AuthMethod.JWT,
        principal="admin-1",
        metadata={"admin_roles": ["operator"]},
    )
    app = _make_app_with_ctx(ctx)
    client = TestClient(app)
    r = client.patch("/tech/degradation/level", json={"mode": "READ_ONLY", "reason": "test"})
    assert r.status_code == 200
    records = [rec for rec in caplog_audit.records if rec.name == "audit_log.admin"]
    assert records, "ожидаем хотя бы одну запись в audit_log.admin"
    rec = records[0]
    assert rec.actor_principal == "admin-1"
    assert "operator" in rec.actor_admin_roles
    assert rec.endpoint == "/tech/degradation/level"
    assert rec.method == "PATCH"
    assert rec.status_code == 200
    assert rec.payload_hash  # sha256 от body
    assert rec.correlation_id == "corr-123"


def test_get_admin_path_does_not_emit_audit(caplog_audit: pytest.LogCaptureFixture) -> None:
    ctx = AuthContext(
        method=AuthMethod.JWT,
        principal="admin-1",
        metadata={"admin_roles": ["operator"]},
    )
    app = _make_app_with_ctx(ctx)
    client = TestClient(app)
    r = client.get("/tech/degradation/snapshot")
    assert r.status_code == 200
    records = [rec for rec in caplog_audit.records if rec.name == "audit_log.admin"]
    assert not records, "GET-запросы не должны попадать в admin-audit"


def test_post_admin_path_emits_audit(caplog_audit: pytest.LogCaptureFixture) -> None:
    ctx = AuthContext(
        method=AuthMethod.JWT,
        principal="ops",
        metadata={"admin_roles": ["super_admin"]},
    )
    app = _make_app_with_ctx(ctx)
    client = TestClient(app)
    r = client.post(
        "/api/v1/admin/resilience-profiles/foo", json={"name": "foo", "retry": {}}
    )
    assert r.status_code == 200
    records = [rec for rec in caplog_audit.records if rec.name == "audit_log.admin"]
    assert records
    assert records[0].endpoint == "/api/v1/admin/resilience-profiles/foo"
    assert "super_admin" in records[0].actor_admin_roles


def test_non_admin_path_skipped(caplog_audit: pytest.LogCaptureFixture) -> None:
    ctx = AuthContext(
        method=AuthMethod.JWT,
        principal="user",
        metadata={},
    )
    app = _make_app_with_ctx(ctx)
    client = TestClient(app)
    r = client.get("/api/v1/users")
    assert r.status_code == 200
    records = [rec for rec in caplog_audit.records if rec.name == "audit_log.admin"]
    assert not records


def test_anonymous_principal_when_ctx_absent(caplog_audit: pytest.LogCaptureFixture) -> None:
    app = _make_app_with_ctx(None)
    client = TestClient(app)
    r = client.patch("/tech/degradation/level", json={"mode": "FULL"})
    assert r.status_code == 200
    records = [rec for rec in caplog_audit.records if rec.name == "audit_log.admin"]
    assert records
    assert records[0].actor_principal == "anonymous"
    assert records[0].actor_admin_roles == []
