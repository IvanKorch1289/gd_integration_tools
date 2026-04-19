"""Аутентификация по API-ключу с поддержкой ротации.

Проверяет ключ через APIKeyManager:
1. Per-client ключи в Redis (с grace period при ротации)
2. Глобальный ключ из настроек (fallback)
"""

from fastapi import Depends, Header, HTTPException

from app.core.security.api_key_manager import APIKeyManager, get_api_key_manager

__all__ = ("require_api_key",)


async def require_api_key(
    x_api_key: str = Header(..., description="API-ключ для авторизации клиента."),
    manager: APIKeyManager = Depends(lambda: get_api_key_manager()),
) -> str:
    """Проверяет API-ключ через APIKeyManager.

    Args:
        x_api_key: Значение заголовка X-API-Key.
        manager: APIKeyManager (injected via DI).

    Returns:
        str: client_id валидного ключа.

    Raises:
        HTTPException: 401 если ключ невалиден.
    """
    key_info = await manager.validate_key(x_api_key)

    if key_info is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return key_info.client_id
