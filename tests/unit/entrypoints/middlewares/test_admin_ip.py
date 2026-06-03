"""Unit tests for IPRestrictionMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.admin_ip import IPRestrictionMiddleware


class TestIPRestrictionMiddleware:
    """Tests for :class:`IPRestrictionMiddleware`."""

    @pytest.fixture
    def middleware(self) -> IPRestrictionMiddleware:
        app = AsyncMock()
        mw = IPRestrictionMiddleware(app)
        return mw

    @pytest.mark.asyncio
    async def test_non_admin_route_bypasses(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Non-admin routes are allowed for any IP."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/public",
                "path": "/public",
                "headers": [(b"host", b"test")],
                "client": ("1.2.3.4", 1234),
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_route_allowed_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with allowed IP passes through."""
        middleware.allowed_ips = {"192.168.1.1"}
        middleware.compiled_patterns = [MagicMock()]
        middleware.compiled_patterns[0].match = MagicMock(return_value=True)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/admin",
                "path": "/admin",
                "headers": [(b"host", b"test")],
                "client": ("192.168.1.1", 1234),
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_route_forbidden_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with disallowed IP raises 403."""
        middleware.allowed_ips = {"192.168.1.1"}
        middleware.compiled_patterns = [MagicMock()]
        middleware.compiled_patterns[0].match = MagicMock(return_value=True)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/admin",
                "path": "/admin",
                "headers": [(b"host", b"test")],
                "client": ("10.0.0.1", 1234),
            }
        )
        call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)

        assert exc_info.value.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_route_allowed_subnet(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with IP inside allowed subnet passes through."""
        middleware.allowed_ips = {"192.168.0.0/24"}
        middleware.compiled_patterns = [MagicMock()]
        middleware.compiled_patterns[0].match = MagicMock(return_value=True)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/admin",
                "path": "/admin",
                "headers": [(b"host", b"test")],
                "client": ("192.168.0.55", 1234),
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_route_invalid_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Invalid client IP is treated as not allowed."""
        middleware.allowed_ips = {"192.168.1.1"}
        middleware.compiled_patterns = [MagicMock()]
        middleware.compiled_patterns[0].match = MagicMock(return_value=True)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/admin",
                "path": "/admin",
                "headers": [(b"host", b"test")],
                "client": ("not-an-ip", 1234),
            }
        )
        call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)

        assert exc_info.value.status_code == 403

    def test_is_ip_allowed_single(self, middleware: IPRestrictionMiddleware) -> None:
        """_is_ip_allowed matches exact IPs."""
        middleware.allowed_ips = {"10.0.0.1", "10.0.0.2"}
        assert middleware._is_ip_allowed("10.0.0.1") is True
        assert middleware._is_ip_allowed("10.0.0.3") is False

    def test_is_ip_allowed_subnet(self, middleware: IPRestrictionMiddleware) -> None:
        """_is_ip_allowed matches subnets."""
        middleware.allowed_ips = {"10.0.0.0/30"}
        assert middleware._is_ip_allowed("10.0.0.1") is True
        assert middleware._is_ip_allowed("10.0.0.5") is False

    def test_is_ip_allowed_invalid(self, middleware: IPRestrictionMiddleware) -> None:
        """_is_ip_allowed returns False for malformed IP."""
        middleware.allowed_ips = {"10.0.0.1"}
        assert middleware._is_ip_allowed("bad-ip") is False

    def test_is_admin_route(self, middleware: IPRestrictionMiddleware) -> None:
        """_is_admin_route uses compiled patterns."""
        pattern = MagicMock()
        pattern.match = MagicMock(return_value=None)
        middleware.compiled_patterns = [pattern]

        assert middleware._is_admin_route("/public") is False
        pattern.match.assert_called_once_with("/public")
