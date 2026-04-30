"""Callbacks для rate-limit (W6 layer cleanup).

Перенесены в ``core/`` чтобы и ``services/decorators/limiting`` (декоратор),
и ``infrastructure/decorators/limiting`` (``init_limiter``) могли
импортировать их без layer-violation: и services, и infrastructure
имеют право зависеть от ``core``.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, Response, status

__all__ = ("default_identifier", "default_callback")


async def default_identifier(request: Request) -> str:
    """Идентификатор клиента для rate-limit (user-id → IP+path)."""
    user = getattr(request, "user", None)
    if user and getattr(user, "id", None):
        return f"user:{user.id}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    return f"ip:{client_ip}:{request.url.path}"


async def default_callback(
    request: Request, response: Response, pexpire: int
) -> None:
    """Обработчик превышения лимита: HTTP 429 с Retry-After."""
    retry_after = max(1, pexpire // 1000)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )
