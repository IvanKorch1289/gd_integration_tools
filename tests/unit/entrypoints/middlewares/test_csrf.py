"""Tests для CSRFMiddleware (S184)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.entrypoints.middlewares.csrf import CSRFMiddleware


class TestCSRFMiddleware:
    """Тесты CSRF protection logic."""

    def setup_method(self) -> None:
        """Common setup."""
        self.app = MagicMock()
        self.middleware = CSRFMiddleware(self.app, enabled=True)
        self.call_next = AsyncMock()

    @pytest.mark.asyncio
    async def test_safe_method_get_bypasses_csrf(self) -> None:
        """GET метод пропускается без CSRF check."""
        request = MagicMock()
        request.method = "GET"

        response = await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_safe_method_head_bypasses_csrf(self) -> None:
        """HEAD метод пропускается."""
        request = MagicMock()
        request.method = "HEAD"

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_safe_method_options_bypasses_csrf(self) -> None:
        """OPTIONS (CORS preflight) пропускается."""
        request = MagicMock()
        request.method = "OPTIONS"

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_post_without_csrf_returns_403(self) -> None:
        """POST без CSRF token → 403."""
        request = MagicMock()
        request.method = "POST"
        request.cookies = {}
        request.headers = {}

        response = await self.middleware.dispatch(request, self.call_next)

        assert response.status_code == 403
        assert not self.call_next.called

    @pytest.mark.asyncio
    async def test_post_with_matching_csrf_passes(self) -> None:
        """POST с matching cookie+header CSRF → pass."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/users"
        request.cookies = {"csrf_token": "abc123"}
        request.headers = {"x-csrf-token": "abc123"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_post_with_mismatched_csrf_returns_403(self) -> None:
        """POST с mismatch cookie vs header CSRF → 403."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/users"
        request.cookies = {"csrf_token": "abc123"}
        request.headers = {"x-csrf-token": "different"}

        response = await self.middleware.dispatch(request, self.call_next)

        assert response.status_code == 403
        assert not self.call_next.called

    @pytest.mark.asyncio
    async def test_post_with_jwt_auth_exempt(self) -> None:
        """POST с JWT auth (Authorization: Bearer) — exempt от CSRF."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/users"
        request.cookies = {}  # no cookie
        request.headers = {"Authorization": "Bearer <jwt-token>"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_post_with_api_key_exempt(self) -> None:
        """POST с X-API-Key — exempt от CSRF."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/users"
        request.cookies = {}
        request.headers = {"X-API-Key": "secret-key"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_webhook_safe_path_bypass(self) -> None:
        """Webhook paths bypass CSRF check."""
        mw = CSRFMiddleware(
            self.app, enabled=True, safe_paths=("/api/v1/webhook/",)
        )
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/webhook/github"
        request.cookies = {}
        request.headers = {}

        await mw.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_disabled_middleware_bypasses_all(self) -> None:
        """Disabled middleware → bypass все checks."""
        mw = CSRFMiddleware(self.app, enabled=False)
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/users"
        request.cookies = {}
        request.headers = {}

        await mw.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_put_with_csrf_passes(self) -> None:
        """PUT (state-changing) с CSRF — pass."""
        request = MagicMock()
        request.method = "PUT"
        request.url.path = "/api/v1/users/123"
        request.cookies = {"csrf_token": "token-xyz"}
        request.headers = {"x-csrf-token": "token-xyz"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_delete_with_csrf_passes(self) -> None:
        """DELETE (state-changing) с CSRF — pass."""
        request = MagicMock()
        request.method = "DELETE"
        request.url.path = "/api/v1/users/123"
        request.cookies = {"csrf_token": "del-token"}
        request.headers = {"x-csrf-token": "del-token"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called

    @pytest.mark.asyncio
    async def test_patch_with_csrf_passes(self) -> None:
        """PATCH (state-changing) с CSRF — pass."""
        request = MagicMock()
        request.method = "PATCH"
        request.url.path = "/api/v1/users/123"
        request.cookies = {"csrf_token": "patch-token"}
        request.headers = {"x-csrf-token": "patch-token"}

        await self.middleware.dispatch(request, self.call_next)
        assert self.call_next.called
