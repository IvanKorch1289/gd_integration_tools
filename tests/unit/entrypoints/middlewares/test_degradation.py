"""Unit tests for DegradationMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.core.resilience.degradation import DegradationMode
from src.backend.entrypoints.middlewares.degradation import (
    DEGRADATION_BYPASS_PREFIXES,
    DegradationMiddleware,
)


class FakeStatus:
    """Fake component status for degradation tests."""

    def __init__(self, last_used_backend: str, degradation: str) -> None:
        self.last_used_backend = last_used_backend
        self.degradation = degradation


class TestDegradationMiddleware:
    """Tests for :class:`DegradationMiddleware`."""

    @pytest.fixture
    def middleware(self) -> DegradationMiddleware:
        return DegradationMiddleware(AsyncMock(), retry_after=30)

    @pytest.mark.asyncio
    async def test_full_mode_passes_through(
        self, middleware: DegradationMiddleware
    ) -> None:
        """FULL mode allows all requests."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.FULL
            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maintenance_blocks_non_essential(
        self, middleware: DegradationMiddleware
    ) -> None:
        """MAINTENANCE mode blocks non-maintenance paths."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock()

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 503
        assert result.headers["Retry-After"] == "30"
        assert result.headers["X-Degradation-Mode"] == "maintenance"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_maintenance_allows_liveness(
        self, middleware: DegradationMiddleware
    ) -> None:
        """MAINTENANCE mode allows /health/liveness."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/health/liveness",
                "path": "/health/liveness",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_essential_only_blocks_api(
        self, middleware: DegradationMiddleware
    ) -> None:
        """ESSENTIAL_ONLY blocks /api paths."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock()

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.ESSENTIAL_ONLY
            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 503
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_only_blocks_writes(
        self, middleware: DegradationMiddleware
    ) -> None:
        """CACHE_ONLY blocks POST/PUT/PATCH/DELETE."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock()

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.CACHE_ONLY
            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 503
        assert result.headers["X-Degradation-Mode"] == "cache-only-no-writes"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_only_allows_reads_and_sets_header(
        self, middleware: DegradationMiddleware
    ) -> None:
        """CACHE_ONLY allows GET and sets X-Degradation-Mode header."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.CACHE_ONLY
            result = await middleware.dispatch(request, call_next)

        assert result is response
        assert result.headers["X-Degradation-Mode"] == "cache_only"
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_only_blocks_writes(
        self, middleware: DegradationMiddleware
    ) -> None:
        """READ_ONLY blocks writes."""
        request = Request(
            {
                "type": "http",
                "method": "DELETE",
                "url": "http://test/api/v1/users/1",
                "path": "/api/v1/users/1",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock()

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.READ_ONLY
            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 503
        assert result.headers["X-Degradation-Mode"] == "read-only"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bypass_prefixes(self, middleware: DegradationMiddleware) -> None:
        """Bypass prefixes allow writes even in degraded mode."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api/v1/audit/events",
                "path": "/api/v1/audit/events",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        with patch(
            "src.backend.core.resilience.degradation.degradation_manager"
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.READ_ONLY
            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_legacy_db_main_fallback_blocks(
        self, middleware: DegradationMiddleware
    ) -> None:
        """Legacy path: db_main in fallback blocks writes."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock()

        with (
            patch(
                "src.backend.core.resilience.degradation.degradation_manager"
            ) as mock_mgr,
            patch(
                "src.backend.core.di.providers.get_resilience_coordinator_provider"
            ) as mock_coord_provider,
        ):
            mock_mgr.current_mode = DegradationMode.FULL
            mock_coord = MagicMock()
            mock_coord.status.return_value = {
                "db_main": FakeStatus("sqlite_ro", "degraded")
            }
            mock_coord_provider.return_value = mock_coord

            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 503
        assert "db_main" in str(result.body)
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_legacy_db_main_primary_allows(
        self, middleware: DegradationMiddleware
    ) -> None:
        """Legacy path: db_main on primary allows writes."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api/v1/users",
                "path": "/api/v1/users",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        with (
            patch(
                "src.backend.core.resilience.degradation.degradation_manager"
            ) as mock_mgr,
            patch(
                "src.backend.core.di.providers.get_resilience_coordinator_provider"
            ) as mock_coord_provider,
        ):
            mock_mgr.current_mode = DegradationMode.FULL
            mock_coord = MagicMock()
            mock_coord.status.return_value = {
                "db_main": FakeStatus("primary", "healthy")
            }
            mock_coord_provider.return_value = mock_coord

            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    def test_is_bypassed(self, middleware: DegradationMiddleware) -> None:
        """_is_bypassed checks prefixes correctly."""
        assert middleware._is_bypassed("/health") is True
        assert middleware._is_bypassed("/api/v1/audit/events") is True
        assert middleware._is_bypassed("/api/v1/users") is False

    def test_build_503(self, middleware: DegradationMiddleware) -> None:
        """_build_503 returns correct JSONResponse structure."""
        resp = middleware._build_503("reason", header="hdr")
        assert resp.status_code == 503
        assert resp.headers["Retry-After"] == "30"
        assert resp.headers["X-Degradation-Mode"] == "hdr"
        assert "degraded" in str(resp.body)
