"""Тесты дедупликации APIKeyMiddleware vs AuthRequiredMiddleware (M-1).

Цель: убедиться, что когда AuthRequiredMiddleware уже установил
``request.state.auth``, APIKeyMiddleware пропускает повторную
валидацию без обращения к ``settings.secure.api_key``.
"""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_api_key_middleware_skips_when_auth_already_set() -> None:
    """state.auth установлен → APIKeyMiddleware вызывает call_next без проверок."""
    from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

    middleware = APIKeyMiddleware(app=AsyncMock())
    middleware.compiled_patterns = []

    request = SimpleNamespace(
        state=SimpleNamespace(auth=SimpleNamespace(method="JWT", principal="alice")),
        url=SimpleNamespace(path="/api/v1/protected"),
        headers={},
    )
    sentinel = object()
    call_next = AsyncMock(return_value=sentinel)

    result = await middleware.dispatch(request, call_next)

    assert result is sentinel
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_api_key_middleware_validates_when_no_auth() -> None:
    """state.auth не установлен → проверяется X-API-Key как раньше."""
    from fastapi import HTTPException

    from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

    middleware = APIKeyMiddleware(app=AsyncMock())
    middleware.compiled_patterns = []

    request = SimpleNamespace(
        state=SimpleNamespace(),
        url=SimpleNamespace(path="/api/v1/protected"),
        headers={},
    )
    call_next = AsyncMock()

    with pytest.raises(HTTPException) as excinfo:
        await middleware.dispatch(request, call_next)
    assert excinfo.value.status_code == 401
    call_next.assert_not_called()
