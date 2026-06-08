"""JWT Introspection endpoint (RFC 7662) — Sprint 16 DoD-7.

POST ``/auth/introspect`` — OAuth2-стиль проверка активности токена.
Reuse: :func:`get_jwt_backend_provider` (singleton joserfc backend) →
:meth:`JwtBackend.decode` (sig + claims + blacklist check).

Response per RFC 7662 §2.2: ``{"active": true|false, ...}``. Для inactive
токенов (истёкших / отозванных / с неверной подписью) возвращается
``{"active": false}`` без дополнительных claims.

RFC: https://datatracker.ietf.org/doc/html/rfc7662
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, status

from src.backend.core.auth.jwt_backend_joserfc import JwtVerificationError
from src.backend.core.di.providers import get_jwt_backend_provider
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("router",)

_logger = get_logger(__name__)
router = APIRouter()

_INTROSPECT_FIELDS = (
    "scope",
    "client_id",
    "username",
    "token_type",
    "exp",
    "iat",
    "nbf",
    "sub",
    "aud",
    "iss",
    "jti",
)


@router.post("/introspect", summary="OAuth2 Token Introspection (RFC 7662)")
async def introspect(
    token: str = Form(..., description="JWT для проверки"),
    token_type_hint: str | None = Form(
        None, description="Игнорируется (only access_token)"
    ),
) -> dict[str, Any]:
    """RFC 7662 token introspection.

    Args:
        token: JWT-токен.
        token_type_hint: Optional hint (только ``access_token``).

    Returns:
        ``{"active": True, scope?, sub?, exp?, jti?, ...}`` для валидных;
        ``{"active": False}`` для истёкших / отозванных / неверных.
    """
    del token_type_hint  # access_token only
    backend = get_jwt_backend_provider()
    if backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT backend not configured",
        )
    try:
        claims = await backend.decode(token)
    except JwtVerificationError as exc:
        _logger.info("Introspect rejected: %s", exc)
        return {"active": False}

    response: dict[str, Any] = {"active": True}
    raw = claims.raw or {}
    for key in _INTROSPECT_FIELDS:
        value = raw.get(key)
        if value is not None:
            response[key] = value
    return response
