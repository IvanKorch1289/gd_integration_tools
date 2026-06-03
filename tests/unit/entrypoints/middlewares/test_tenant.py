"""Unit tests for TenantMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response

from src.backend.entrypoints.middlewares.tenant import TenantMiddleware


class TestTenantMiddleware:
    """Tests for :class:`TenantMiddleware`."""

    @pytest.fixture
    def middleware(self) -> TenantMiddleware:
        return TenantMiddleware(AsyncMock(), default_tenant="default")

    @pytest.mark.asyncio
    async def test_header_tenant_used(self, middleware: TenantMiddleware) -> None:
        """X-Tenant-ID header is extracted and propagated."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test"), (b"x-tenant-id", b"tenant-42")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        assert request.state.tenant_id == "tenant-42"
        assert result.headers["X-Tenant-ID"] == "tenant-42"
        mock_setter.assert_called_once_with(tenant_id="tenant-42")

    @pytest.mark.asyncio
    async def test_state_tenant_fallback(self, middleware: TenantMiddleware) -> None:
        """If no header, uses request.state.tenant_id."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        request.state.tenant_id = "state-tenant"
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            result = await middleware.dispatch(request, call_next)

        assert request.state.tenant_id == "state-tenant"
        assert result.headers["X-Tenant-ID"] == "state-tenant"
        mock_setter.assert_called_once_with(tenant_id="state-tenant")

    @pytest.mark.asyncio
    async def test_default_tenant_fallback(self, middleware: TenantMiddleware) -> None:
        """If no header and no state, falls back to default tenant."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            result = await middleware.dispatch(request, call_next)

        assert request.state.tenant_id == "default"
        assert result.headers["X-Tenant-ID"] == "default"
        mock_setter.assert_called_once_with(tenant_id="default")

    @pytest.mark.asyncio
    async def test_header_priority_over_state(
        self, middleware: TenantMiddleware
    ) -> None:
        """Header takes priority over request.state.tenant_id."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test"), (b"x-tenant-id", b"header-tenant")],
            }
        )
        request.state.tenant_id = "state-tenant"
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            result = await middleware.dispatch(request, call_next)

        assert request.state.tenant_id == "header-tenant"
        assert result.headers["X-Tenant-ID"] == "header-tenant"
