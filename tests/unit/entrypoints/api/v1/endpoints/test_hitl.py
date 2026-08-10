"""cycle-6/D-AUDIT-607: HITL permission и tenant isolation regressions."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.api.v1.endpoints import hitl
from src.backend.services.workflows.hitl_service import (
    HitlPendingSignal,
    HitlService,
    InMemoryHitlSignalStore,
)

pytestmark = pytest.mark.unit


def _signal(*, signal_id: str, tenant_id: str) -> HitlPendingSignal:
    """Создаёт минимальный pending signal для API-теста."""
    return HitlPendingSignal(
        signal_id=signal_id,
        workflow_id=f"workflow-{signal_id}",
        tenant_id=tenant_id,
        signal_name="hitl_approve",
        initiator="test",
        title="Review",
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Создаёт HITL API с optional test auth context из headers."""
    app = FastAPI()
    store = InMemoryHitlSignalStore()
    app.state.hitl_service = HitlService(store=store)

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        tenant_id = request.headers.get("X-Test-Tenant")
        if tenant_id is not None:
            request.state.auth = AuthContext(
                AuthMethod.JWT,
                "operator",
                {"permissions": ["hitl.resolve"], "tenant_id": tenant_id},
            )
        return await call_next(request)

    app.include_router(hitl.router, prefix="/hitl")
    with TestClient(app) as test_client:
        test_client.app.state.hitl_store = store
        yield test_client


def test_hitl_resolve_without_auth_returns_401(client: TestClient) -> None:
    """Неаутентифицированный resolve отклоняется до handler-а."""
    response = client.post(
        "/hitl/missing/resolve", json={"action": "approve", "resolved_by": "operator"},
    )

    assert response.status_code == 401


def test_hitl_resolve_cross_tenant_returns_403(client: TestClient) -> None:
    """Оператор tenant A не разрешает signal tenant B."""
    store = client.app.state.hitl_store
    client.portal.call(store.put, _signal(signal_id="signal-b", tenant_id="tenant-b"))

    response = client.post(
        "/hitl/signal-b/resolve",
        headers={"X-Test-Tenant": "tenant-a"},
        json={"action": "approve", "resolved_by": "operator-a"},
    )

    assert response.status_code == 403


def test_hitl_resolve_own_tenant_returns_200(client: TestClient) -> None:
    """Оператор с permission разрешает signal своего tenant."""
    store = client.app.state.hitl_store
    client.portal.call(store.put, _signal(signal_id="signal-a", tenant_id="tenant-a"))

    response = client.post(
        "/hitl/signal-a/resolve",
        headers={"X-Test-Tenant": "tenant-a"},
        json={"action": "approve", "resolved_by": "operator-a"},
    )

    assert response.status_code == 200
    assert response.json()["resolved_action"] == "approve"
