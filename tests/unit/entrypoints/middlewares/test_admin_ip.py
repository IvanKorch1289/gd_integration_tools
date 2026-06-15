"""Unit tests for IPRestrictionMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.entrypoints.middlewares.admin_ip import IPRestrictionMiddleware


class TestIPRestrictionMiddleware:
    """Tests for :class:`IPRestrictionMiddleware`."""

    @pytest.fixture
    def middleware(self) -> IPRestrictionMiddleware:
        app = AsyncMock()
        mw = IPRestrictionMiddleware(app)
        store = get_ip_restriction_store()
        store.update_admin(set(), [])
        store.clear_route_rules()
        return mw

    def _request(self, path: str, client_ip: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "url": f"http://test{path}",
                "path": path,
                "headers": [(b"host", b"test")],
                "client": (client_ip, 1234),
            }
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_non_admin_route_bypasses(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Non-admin routes are allowed for any IP."""
        request = self._request("/public", "1.2.3.4")
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_allowed_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with allowed IP passes through."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        request = self._request("/admin/users", "192.168.1.1")
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_forbidden_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with disallowed IP raises 403."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        request = self._request("/admin/users", "10.0.0.1")
        call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)

        assert exc_info.value.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_allowed_subnet(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Admin route with IP inside allowed subnet passes through."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.0.0/24"}, admin_routes=["/admin/*"])

        request = self._request("/admin/users", "192.168.0.55")
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_per_route_rule_takes_priority(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Per-route rule is checked before global admin rule."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/admin/special", ["192.168.1.1"])

        request = self._request("/admin/special", "192.168.1.1")
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_per_route_rule_forbids_admin_ip(
        self, middleware: IPRestrictionMiddleware
    ) -> None:
        """Per-route rule can forbid an IP that is allowed globally."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/admin/special", ["192.168.1.1"])

        request = self._request("/admin/special", "10.0.0.1")
        call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_invalid_client_ip(self, middleware: IPRestrictionMiddleware) -> None:
        """Invalid client IP is treated as not allowed."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        request = self._request("/admin/users", "not-an-ip")
        call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, call_next)

        assert exc_info.value.status_code == 403
