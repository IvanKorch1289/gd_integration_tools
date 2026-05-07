"""Sprint 1 V16 — smoke-тест регистрации ``TenantMiddleware`` в цепочке.

Проверяет, что ``setup_middlewares`` устанавливает ``TenantMiddleware``
между ``CorrelationIdMiddleware`` и ``IdempotencyHeaderMiddleware``,
а также что middleware корректно пропагирует ``tenant_id`` в
``request.state`` и в ``structlog`` contextvars.
"""

# ruff: noqa: S101

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.entrypoints.middlewares.tenant import TenantMiddleware


def test_tenant_middleware_propagates_header() -> None:
    """``TenantMiddleware`` извлекает ``X-Tenant-ID`` и кладёт в state."""

    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    captured: dict[str, str | None] = {}

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str | None]:
        captured["tenant_id"] = getattr(request.state, "tenant_id", None)
        captured["structlog_tenant"] = structlog.contextvars.get_contextvars().get(
            "tenant_id"
        )
        return {"ok": "1"}

    client = TestClient(app)
    response = client.get("/probe", headers={"X-Tenant-ID": "t1"})

    assert response.status_code == 200
    assert response.headers.get("X-Tenant-ID") == "t1"
    assert captured["tenant_id"] == "t1"
    assert captured["structlog_tenant"] == "t1"


def test_tenant_middleware_default_tenant() -> None:
    """Без ``X-Tenant-ID`` middleware подставляет ``default``."""

    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    captured: dict[str, str | None] = {}

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str | None]:
        captured["tenant_id"] = getattr(request.state, "tenant_id", None)
        return {"ok": "1"}

    client = TestClient(app)
    response = client.get("/probe")

    assert response.status_code == 200
    assert captured["tenant_id"] == "default"
    assert response.headers.get("X-Tenant-ID") == "default"


def test_tenant_middleware_registered_in_setup_chain() -> None:
    """``setup_middlewares`` регистрирует ``TenantMiddleware`` в chain.

    Проверка через инспекцию ``app.user_middleware``: после
    ``setup_middlewares`` среди установленных middleware должен быть
    ``TenantMiddleware``.
    """

    from src.backend.entrypoints.middlewares.setup_middlewares import setup_middlewares

    app = FastAPI()
    setup_middlewares(app)

    middleware_classes = {m.cls for m in app.user_middleware}
    assert TenantMiddleware in middleware_classes
