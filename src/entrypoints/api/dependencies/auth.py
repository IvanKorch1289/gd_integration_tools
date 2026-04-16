from fastapi import Header

__all__ = ("require_api_key",)


async def require_api_key(
    x_api_key: str = Header(..., description="API-ключ для авторизации клиента."),
) -> str:
    """
    Обязательная dependency для проверки наличия API-ключа.

    Пока dependency лишь валидирует наличие заголовка.
    Позже сюда можно добавить:
    - проверку ключа в БД/Redis;
    - rate limit по ключу;
    - audit logging;
    - определение client/service identity.

    Args:
        x_api_key: Значение заголовка X-API-Key.

    Returns:
        str: Переданный API-ключ.
    """
    return x_api_key
