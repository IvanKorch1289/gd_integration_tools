"""Integration-smoke V7: AuthRequiredMiddleware закрывает non-public endpoints.

Сценарий: на минимальном FastAPI-приложении с парой routes (один public,
один non-public) проверяем, что middleware блокирует non-public без
credentials и пропускает public.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware


def _build_app(verifier=None) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/api/v1/orders")
    def orders(request: Request) -> dict[str, str]:
        auth = getattr(request.state, "auth", None)
        return {"principal": auth.principal if auth else ""}

    # Подменяем верификаторы.
    import src.backend.entrypoints.api.dependencies.auth_selector as auth_selector

    original = auth_selector._VERIFIERS
    auth_selector._VERIFIERS = (  # type: ignore[assignment]
        {AuthMethod.API_KEY: verifier} if verifier else {}
    )

    @app.on_event("shutdown")
    def restore() -> None:
        auth_selector._VERIFIERS = original  # type: ignore[assignment]

    app.add_middleware(AuthRequiredMiddleware)
    return app


def test_health_accessible_without_auth() -> None:
    app = _build_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_non_public_blocked_without_auth() -> None:
    app = _build_app()
    client = TestClient(app)
    response = client.get("/api/v1/orders")
    assert response.status_code == 401


def test_non_public_passes_with_valid_credentials() -> None:
    async def verifier(request: Request) -> AuthContext | None:
        if request.headers.get("X-API-Key") == "valid":
            return AuthContext(AuthMethod.API_KEY, "client-1")
        return None

    app = _build_app(verifier)
    client = TestClient(app)
    response = client.get("/api/v1/orders", headers={"X-API-Key": "valid"})
    assert response.status_code == 200
    assert response.json() == {"principal": "client-1"}


def test_non_public_blocked_with_invalid_credentials() -> None:
    async def verifier(request: Request) -> AuthContext | None:
        return None

    app = _build_app(verifier)
    client = TestClient(app)
    response = client.get("/api/v1/orders", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
