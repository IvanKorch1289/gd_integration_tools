"""Аутентификация по API-ключу с поддержкой ротации.

Проверяет ключ через APIKeyManager:
1. Per-client ключи в Redis (с grace period при ротации)
2. Глобальный ключ из настроек (fallback)

Wave 6.5a: ``APIKeyManager`` резолвится через
``core.di.providers.get_api_key_manager_provider`` (lazy importlib),
чтобы entrypoints/ не импортировал ``infrastructure/`` напрямую.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException

from src.core.di.providers import get_api_key_manager_provider

__all__ = ("require_api_key",)


def _resolve_api_key_manager() -> Any:
    """FastAPI Depends-фабрика — lazy resolve APIKeyManager."""
    return get_api_key_manager_provider()


async def require_api_key(
    x_api_key: str = Header(..., description="API-ключ для авторизации клиента."),
    manager: Any = Depends(_resolve_api_key_manager),
) -> str:
    """Проверяет API-ключ через APIKeyManager.

    Args:
        x_api_key: Значение заголовка X-API-Key.
        manager: APIKeyManager (injected via DI provider).

    Returns:
        str: client_id валидного ключа.

    Raises:
        HTTPException: 401 если ключ невалиден.
    """
    key_info = await manager.validate_key(x_api_key)

    if key_info is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return key_info.client_id
