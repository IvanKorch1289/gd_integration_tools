"""Unit tests for SecurityHeadersMiddleware.

Verifies that security headers (X-Content-Type-Options, X-Frame-Options,
Strict-Transport-Security, CSP, Permissions-Policy) are injected into every
HTTP response, override conflicting downstream headers, and that non-HTTP
scopes (e.g. WebSocket) pass through unmodified.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.responses import Response

from src.backend.entrypoints.middlewares.security_headers import (
    SecurityHeadersMiddleware,
)

# Expected header set injected by the middleware.
EXPECTED_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'",
    "Permissions-Policy": "geolocation=(), microphone=()",
}


def _make_middleware() -> tuple[SecurityHeadersMiddleware, AsyncMock]:
    """Build a middleware with a mocked call_next returning a plain Response."""
    app = AsyncMock()
    mw = SecurityHeadersMiddleware(app)
    return mw, app


@pytest.mark.asyncio
async def test_x_content_type_options_nosniff() -> None:
    """X-Content-Type-Options is set to nosniff to prevent MIME-sniffing."""
    mw, _ = _make_middleware()
    request = MagicMock()
    call_next = AsyncMock(return_value=Response(content=b"ok"))
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_deny() -> None:
    """X-Frame-Options is set to DENY to prevent clickjacking."""
    mw, _ = _make_middleware()
    request = MagicMock()
    call_next = AsyncMock(return_value=Response(content=b"ok"))
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Frame-Options"] == "DENY"


@pytest.mark.asyncio
async def test_strict_transport_security_header() -> None:
    """HSTS header is present with max-age and includeSubDomains."""
    mw, _ = _make_middleware()
    request = MagicMock()
    call_next = AsyncMock(return_value=Response(content=b"ok"))
    result = await mw.dispatch(request, call_next)
    hsts = result.headers["Strict-Transport-Security"]
    assert "max-age=63072000" in hsts
    assert "includeSubDomains" in hsts


@pytest.mark.asyncio
async def test_all_security_headers_present() -> None:
    """The full expected security header set is injected."""
    mw, _ = _make_middleware()
    request = MagicMock()
    call_next = AsyncMock(return_value=Response(content=b"ok"))
    result = await mw.dispatch(request, call_next)
    for header, expected_value in EXPECTED_HEADERS.items():
        assert result.headers[header] == expected_value, (
            f"header {header!r} mismatch"
        )


@pytest.mark.asyncio
async def test_headers_override_downstream_defaults() -> None:
    """Security headers override conflicting values set downstream.

    The middleware unconditionally updates the response, so a weaker
    X-Frame-Options set by an inner handler is replaced with DENY.
    """
    mw, _ = _make_middleware()
    request = MagicMock()
    weak_response = Response(content=b"ok")
    weak_response.headers["X-Frame-Options"] = "SAMEORIGIN"
    weak_response.headers["X-Content-Type-Options"] = "text/html"
    call_next = AsyncMock(return_value=weak_response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Frame-Options"] == "DENY"
    assert result.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_non_http_scope_passthrough() -> None:
    """Non-HTTP (e.g. WebSocket) scopes pass through without header injection.

    BaseHTTPMiddleware only invokes dispatch for "http" scopes; all other
    scope types are forwarded directly to the wrapped application.
    """
    inner_app = AsyncMock()
    mw = SecurityHeadersMiddleware(inner_app)
    scope = {"type": "websocket", "path": "/ws", "headers": []}
    receive = AsyncMock()
    send = AsyncMock()
    await mw(scope, receive, send)
    # Inner app receives the scope unchanged.
    inner_app.assert_awaited_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_headers_added_to_error_response() -> None:
    """Security headers are present even on non-2xx responses."""
    mw, _ = _make_middleware()
    request = MagicMock()
    call_next = AsyncMock(return_value=Response(status_code=500, content=b"err"))
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Content-Type-Options"] == "nosniff"
    assert result.headers["X-Frame-Options"] == "DENY"
