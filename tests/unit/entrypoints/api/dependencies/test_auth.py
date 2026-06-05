"""Unit-тесты для ``src.backend.entrypoints.api.dependencies.auth``."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.backend.core.di.providers import auth as auth_providers
from src.backend.entrypoints.api.dependencies import auth as auth_dep


@pytest.fixture
def auth_module() -> Any:
    return auth_dep


@pytest.fixture(autouse=True)
def _reset_api_key_provider_override() -> Any:
    """Сбрасываем override менеджера ключей после каждого теста."""
    yield
    auth_providers.set_api_key_manager_provider(None)


@pytest.mark.unit
class TestResolveApiKeyManager:
    def test_resolve_returns_overridden_manager(self, auth_module: Any) -> None:
        sentinel = object()
        auth_providers.set_api_key_manager_provider(sentinel)

        manager = auth_module._resolve_api_key_manager()

        assert manager is sentinel


@pytest.mark.unit
class TestRequireApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_client_id(self, auth_module: Any) -> None:
        class _KeyInfo:
            client_id = "client-42"

        manager = AsyncMock()
        manager.validate_key.return_value = _KeyInfo()

        result = await auth_module.require_api_key(
            x_api_key="valid-secret", manager=manager
        )

        assert result == "client-42"
        manager.validate_key.assert_awaited_once_with("valid-secret")

    @pytest.mark.asyncio
    async def test_invalid_key_raises_401(self, auth_module: Any) -> None:
        manager = AsyncMock()
        manager.validate_key.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await auth_module.require_api_key(
                x_api_key="invalid-secret", manager=manager
            )

        assert exc_info.value.status_code == 401
        assert "Invalid API key" in exc_info.value.detail
