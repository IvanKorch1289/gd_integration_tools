"""Tests for RpaPolicyMiddleware (S171 M6 — security middleware).

Deny-by-default policy для /api/v1/rpa/* endpoints:
- Block RCE-shaped operations unless explicit role granted
- Audit all RPA requests (success and deny)
- Optional IP allowlist
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRpaPolicyMiddleware:
    def test_processor_instantiates(self) -> None:
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware
        mw = RpaPolicyMiddleware(app=MagicMock())
        assert mw is not None

    @pytest.mark.asyncio
    async def test_blocks_rpa_path_without_role(self) -> None:
        """/api/v1/rpa/* без role 'rpa.admin' → 403."""
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware
        mw = RpaPolicyMiddleware(app=MagicMock())

        # Mock request
        request = MagicMock()
        request.url.path = "/api/v1/rpa/shell/exec"
        request.headers = {"x-roles": "user"}
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.method = "POST"

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        # Patch the response helper
        with patch(
            "starlette.responses.JSONResponse"
        ) as mock_json:
            mock_json.return_value = MagicMock(status_code=403)
            response = await mw.dispatch(request, call_next)
        call_next.assert_not_called()  # blocked
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_allows_rpa_path_with_role(self) -> None:
        """/api/v1/rpa/* WITH role 'rpa.admin' → pass through."""
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware
        mw = RpaPolicyMiddleware(app=MagicMock())

        request = MagicMock()
        request.url.path = "/api/v1/rpa/shell/exec"
        request.headers = {"x-roles": "user,rpa.admin"}
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.method = "POST"

        expected_response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=expected_response)
        response = await mw.dispatch(request, call_next)
        call_next.assert_called_once()
        assert response is expected_response

    @pytest.mark.asyncio
    async def test_passes_through_non_rpa_path(self) -> None:
        """/api/v1/users/* → без проверки."""
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware
        mw = RpaPolicyMiddleware(app=MagicMock())

        request = MagicMock()
        request.url.path = "/api/v1/users/list"
        request.headers = {}
        request.state = MagicMock()

        expected_response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=expected_response)
        response = await mw.dispatch(request, call_next)
        call_next.assert_called_once()
        assert response is expected_response
