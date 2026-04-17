"""Аутентификация по API-ключу с поддержкой ротации.

Проверяет ключ через APIKeyManager:
1. Per-client ключи в Redis (с grace period при ротации)
2. Глобальный ключ из настроек (fallback)
"""

from fastapi import Header, HTTPException

__all__ = ("require_api_key",)


async def require_api_key(
    x_api_key: str = Header(..., description="API-ключ для авторизации клиента."),
) -> str:
    """Проверяет API-ключ через APIKeyManager.

    Args:
        x_api_key: Значение заголовка X-API-Key.

    Returns:
        str: client_id валидного ключа.

    Raises:
        HTTPException: 401 если ключ невалиден.
    """
    from app.core.security.api_key_manager import get_api_key_manager

    manager = get_api_key_manager()
    key_info = await manager.validate_key(x_api_key)

    if key_info is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return key_info.client_id
