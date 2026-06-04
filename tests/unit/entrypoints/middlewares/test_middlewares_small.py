"""Unit tests for small middleware modules."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.auth_method_header import (
    AuthMethodHeaderMiddleware,
)
from src.backend.entrypoints.middlewares.blocked_routes import (
    BlockedRoutesMiddleware,
    blocked_routes,
)
from src.backend.entrypoints.middlewares.correlation import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
)
from src.backend.entrypoints.middlewares.request_id import RequestIDMiddleware
from src.backend.entrypoints.middlewares.security_headers import (
    SecurityHeadersMiddleware,
)
from src.backend.entrypoints.middlewares.versioning import APIVersion


# ─── AuthMethodHeaderMiddleware ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_method_header_with_method() -> None:
    app = AsyncMock()
    mw = AuthMethodHeaderMiddleware(app)
    request = MagicMock()
    request.state.auth = MagicMock()
    request.state.auth.method = MagicMock()
    request.state.auth.method.value = "jwt"
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Auth-Method"] == "jwt"


@pytest.mark.asyncio
async def test_auth_method_header_no_auth() -> None:
    app = AsyncMock()
    mw = AuthMethodHeaderMiddleware(app)
    request = MagicMock()
    request.state.auth = None
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert "X-Auth-Method" not in result.headers


# ─── BlockedRoutesMiddleware ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_routes_blocked() -> None:
    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/blocked"
    blocked_routes.add("/blocked")
    call_next = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await mw.dispatch(request, call_next)
    assert exc_info.value.status_code == 403
    blocked_routes.discard("/blocked")


@pytest.mark.asyncio
async def test_blocked_routes_allowed() -> None:
    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/allowed"
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result is response


# ─── CorrelationIdMiddleware re-export ──────────────────────────────────────


def test_correlation_header_constant() -> None:
    assert CORRELATION_HEADER == "X-Correlation-ID"


def test_correlation_middleware_importable() -> None:
    assert CorrelationIdMiddleware is not None


# ─── RequestIDMiddleware ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_generates_ids() -> None:
    app = AsyncMock()
    mw = RequestIDMiddleware(app)
    request = Request(
        {"type": "http", "method": "GET", "url": "http://test/", "headers": []}
    )
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert "X-Request-ID" in result.headers
    assert "X-Correlation-ID" in result.headers
    assert len(result.headers["X-Request-ID"]) == 32


@pytest.mark.asyncio
async def test_request_id_preserves_existing() -> None:
    app = AsyncMock()
    mw = RequestIDMiddleware(app)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "url": "http://test/",
            "headers": [
                (b"x-request-id", b"req-123"),
                (b"x-correlation-id", b"corr-456"),
            ],
        }
    )
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Request-ID"] == "req-123"
    assert result.headers["X-Correlation-ID"] == "corr-456"


# ─── SecurityHeadersMiddleware ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers() -> None:
    app = AsyncMock()
    mw = SecurityHeadersMiddleware(app)
    request = MagicMock()
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Frame-Options"] == "DENY"
    assert result.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" in result.headers


# ─── APIVersion ─────────────────────────────────────────────────────────────


def test_api_version_headers() -> None:
    v = APIVersion(version="1.0")
    assert v.as_headers() == {"API-Version": "1.0"}


def test_api_version_deprecated() -> None:
    v = APIVersion(version="1.0", deprecated=True)
    assert v.as_headers()["Deprecation"] == "true"


def test_api_version_sunset() -> None:
    v = APIVersion(version="1.0", sunset="2025-01-01")
    assert v.as_headers()["Sunset"] == "2025-01-01"
