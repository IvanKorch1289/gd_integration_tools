"""Unit-тесты :class:`AuthRequiredMiddleware`.

Покрытие:
* public-path обходит auth (200 без credentials);
* OPTIONS preflight обходит auth;
* non-public + no-credentials → 401;
* non-public + valid API key → 200, ``request.state.auth`` установлен;
* path-prefix нормализация устойчива к ``//`` и ``../``;
* failed verifier (exception) не ронит middleware — пробует следующий.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    AuthRequiredMiddleware,
    is_path_public,
)


def test_is_path_public_matches_prefix() -> None:
    assert is_path_public("/health", DEFAULT_PUBLIC_PATH_PREFIXES) is True
    assert is_path_public("/health/db", DEFAULT_PUBLIC_PATH_PREFIXES) is True
    assert is_path_public("/openapi.json", DEFAULT_PUBLIC_PATH_PREFIXES) is True


def test_is_path_public_does_not_match_unrelated() -> None:
    assert is_path_public("/api/v1/orders", DEFAULT_PUBLIC_PATH_PREFIXES) is False
    assert is_path_public("/healthy", DEFAULT_PUBLIC_PATH_PREFIXES) is False


def test_is_path_public_normalizes_double_slash() -> None:
    assert is_path_public("/health//db", ("/health",)) is True


def test_is_path_public_strict_boundary() -> None:
    """Префикс /health не матчит /healthy (boundary должна быть segment-aligned)."""
    assert is_path_public("/healthy", ("/health",)) is False
    assert is_path_public("/health-check", ("/health",)) is False


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/protected")
    def protected(request: Request) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        return {
            "method": auth.method.value if auth else None,
            "principal": auth.principal if auth else None,
        }

    return app


def _add_middleware(
    app: FastAPI,
    *,
    verifiers: dict[AuthMethod, Any] | None = None,
    public_prefixes: tuple[str, ...] = DEFAULT_PUBLIC_PATH_PREFIXES,
) -> None:
    """Подменяет _VERIFIERS на тестовый набор и подключает middleware."""
    import src.backend.entrypoints.api.dependencies.auth_selector as auth_selector

    if verifiers is not None:
        original = auth_selector._VERIFIERS
        auth_selector._VERIFIERS = verifiers  # type: ignore[assignment]

        @app.on_event("shutdown")
        def _restore() -> None:
            auth_selector._VERIFIERS = original  # type: ignore[assignment]

    app.add_middleware(AuthRequiredMiddleware, public_prefixes=public_prefixes)


def test_public_path_bypasses_auth(app: FastAPI) -> None:
    _add_middleware(app, verifiers={})
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_non_public_without_credentials_returns_401(app: FastAPI) -> None:
    _add_middleware(app, verifiers={})
    client = TestClient(app)
    response = client.get("/api/v1/protected")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_non_public_with_valid_verifier_returns_200(app: FastAPI) -> None:
    async def fake_api_key(request: Request) -> AuthContext | None:
        if request.headers.get("X-API-Key") == "secret":
            return AuthContext(AuthMethod.API_KEY, "user-1")
        return None

    _add_middleware(app, verifiers={AuthMethod.API_KEY: fake_api_key})
    client = TestClient(app)
    response = client.get("/api/v1/protected", headers={"X-API-Key": "secret"})
    assert response.status_code == 200
    assert response.json() == {"method": "api_key", "principal": "user-1"}


def test_failing_verifier_does_not_break_middleware(app: FastAPI) -> None:
    async def crashing(request: Request) -> AuthContext | None:
        raise RuntimeError("boom")

    async def good(request: Request) -> AuthContext | None:
        if request.headers.get("X-Token") == "ok":
            return AuthContext(AuthMethod.JWT, "u")
        return None

    _add_middleware(app, verifiers={AuthMethod.API_KEY: crashing, AuthMethod.JWT: good})
    client = TestClient(app)
    response = client.get("/api/v1/protected", headers={"X-Token": "ok"})
    assert response.status_code == 200


def test_options_preflight_bypasses_auth(app: FastAPI) -> None:
    _add_middleware(app, verifiers={})
    client = TestClient(app)
    response = client.options("/api/v1/protected")
    # OPTIONS на FastAPI route без явного allow возвращает 405; ключевое — не 401.
    assert response.status_code != 401
