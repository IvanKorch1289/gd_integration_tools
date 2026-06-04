"""Unit-тесты JWT Introspection endpoint (RFC 7662) — Sprint 16 DoD-7."""
# ruff: noqa: S101

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.auth.jwt_backend_joserfc import JwtClaims, JwtVerificationError


@pytest.fixture
def endpoint_module() -> Any:
    """Endpoint-модуль auth_introspect."""
    return importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.auth_introspect"
    )


def test_module_importable(endpoint_module: Any) -> None:
    """Endpoint-модуль импортируется без ошибок."""
    assert hasattr(endpoint_module, "router")


def test_router_has_introspect_route(endpoint_module: Any) -> None:
    """Router регистрирует POST /introspect."""
    routes = getattr(endpoint_module.router, "routes", [])
    paths = {getattr(r, "path", "") for r in routes}
    assert "/introspect" in paths, f"Ожидался /introspect; найдено: {sorted(paths)}"


class _FakeBackend:
    """Fake JwtBackend для тестов: настраиваемый ответ на decode()."""

    def __init__(
        self, *, claims: JwtClaims | None = None, exc: Exception | None = None
    ) -> None:
        self._claims = claims
        self._exc = exc

    async def decode(self, token: str) -> JwtClaims:
        if self._exc is not None:
            raise self._exc
        assert self._claims is not None
        return self._claims


@pytest.mark.asyncio
async def test_introspect_active_token_returns_claims(endpoint_module: Any) -> None:
    """Валидный токен → active=true + поля из claims."""
    claims = JwtClaims(
        sub="user-1",
        iss="https://idp.example.com",
        aud="api",
        exp=9999999999,
        jti="jti-123",
        raw={
            "sub": "user-1",
            "iss": "https://idp.example.com",
            "aud": "api",
            "exp": 9999999999,
            "iat": 1700000000,
            "jti": "jti-123",
            "scope": "read write",
            "client_id": "client-x",
        },
    )
    backend = _FakeBackend(claims=claims)

    with patch.object(
        endpoint_module, "get_jwt_backend_provider", return_value=backend
    ):
        result = await endpoint_module.introspect(
            token="valid-jwt", token_type_hint=None
        )

    assert result["active"] is True
    assert result["sub"] == "user-1"
    assert result["jti"] == "jti-123"
    assert result["scope"] == "read write"
    assert result["client_id"] == "client-x"
    assert result["exp"] == 9999999999
    assert result["iss"] == "https://idp.example.com"


@pytest.mark.asyncio
async def test_introspect_expired_token_returns_inactive(endpoint_module: Any) -> None:
    """Истёкший токен → active=false без раскрытия claims."""
    backend = _FakeBackend(exc=JwtVerificationError("JWT истёк"))

    with patch.object(
        endpoint_module, "get_jwt_backend_provider", return_value=backend
    ):
        result = await endpoint_module.introspect(
            token="expired-jwt", token_type_hint=None
        )

    assert result == {"active": False}


@pytest.mark.asyncio
async def test_introspect_revoked_token_returns_inactive(endpoint_module: Any) -> None:
    """Отозванный токен (blacklist) → active=false."""
    backend = _FakeBackend(exc=JwtVerificationError("JWT отозван (blacklist)"))

    with patch.object(
        endpoint_module, "get_jwt_backend_provider", return_value=backend
    ):
        result = await endpoint_module.introspect(
            token="revoked-jwt", token_type_hint=None
        )

    assert result == {"active": False}


@pytest.mark.asyncio
async def test_introspect_no_backend_503(endpoint_module: Any) -> None:
    """Backend not configured → HTTP 503."""
    from fastapi import HTTPException

    with patch.object(endpoint_module, "get_jwt_backend_provider", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await endpoint_module.introspect(token="any", token_type_hint=None)

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_introspect_omits_missing_claims(endpoint_module: Any) -> None:
    """Если raw не содержит optional поля — они опущены (per RFC)."""
    claims = JwtClaims(
        sub="user-min", iss=None, aud=None, exp=None, jti=None, raw={"sub": "user-min"}
    )
    backend = _FakeBackend(claims=claims)

    with patch.object(
        endpoint_module, "get_jwt_backend_provider", return_value=backend
    ):
        result = await endpoint_module.introspect(
            token="minimal-jwt", token_type_hint=None
        )

    assert result["active"] is True
    assert result["sub"] == "user-min"
    assert "exp" not in result
    assert "jti" not in result
    assert "scope" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
