"""Общие identifier/callback для rate-limit поверх ``fastapi_limiter``."""

from __future__ import annotations

from fastapi import HTTPException, Request, Response, status

__all__ = ("default_callback", "default_identifier")


async def default_identifier(request: Request) -> str:
    """Идентификатор клиента для rate-limit (user-id → IP+path).

    2026-10-15 fix (regression, найден реальным E2E): ``request.user`` — не
    простой атрибут, а property Starlette, которая бросает ``AssertionError``,
    если AuthenticationMiddleware не положил ``scope["user"]``.
    ``getattr(request, "user", None)`` это НЕ гасит — default в getattr
    срабатывает только на ``AttributeError``. В итоге rate-limit dependency
    роняла 500 (``internal_error``) на каждом запросе без установленного
    auth-middleware, включая ``POST /api/v1/invocations``.

    Читаем ``request.scope`` напрямую: это обычный ASGI-scope dict без
    property-ловушек. Тот же контракт, что и у AuthenticationMiddleware:
    он кладёт объект пользователя именно в ``scope["user"]``.
    """
    user = request.scope.get("user")
    if user is not None and getattr(user, "id", None):
        return f"user:{user.id}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    return f"ip:{client_ip}:{request.url.path}"


async def default_callback(request: Request, response: Response, pexpire: int) -> None:
    """Обработчик превышения лимита: HTTP 429 с Retry-After."""
    retry_after = max(1, pexpire // 1000)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )
