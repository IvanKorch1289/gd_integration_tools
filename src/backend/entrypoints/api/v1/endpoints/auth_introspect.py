"""JWT Introspection endpoint (RFC 7662) — Sprint 16 DoD-7.

POST ``/auth/introspect`` — OAuth2-стиль проверка активности токена.

S165 W2: refactored to use AuthFacade (Rule 1: single entry per
auth concern). Replaces direct ``get_jwt_backend_provider()`` + ``JwtBackend.decode()``
with ``AuthFacade.verify_request()``.

Response per RFC 7662 §2.2: ``{"active": true|false, ...}``. Для inactive
токенов (истёкших / отозванных / с неверной подписью) возвращается
``{"active": false}`` без дополнительных claims.

RFC: https://datatracker.ietf.org/doc/html/rfc7662
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form

from src.backend.core.auth.facade import get_auth_facade
from src.backend.core.logging import get_logger

__all__ = ("router",)

_logger = get_logger(__name__)
router = APIRouter()

_INTROSPECT_FIELDS = (
    "scope", "client_id", "username", "token_type",
    "exp", "iat", "nbf", "sub", "aud", "iss", "jti",
)


@router.post("/introspect", summary="OAuth2 Token Introspection (RFC 7662)")
async def introspect(
    token: str = Form(..., description="JWT для проверки"),
    token_type_hint: str | None = Form(None, description="Игнорируется (only access_token)"),
) -> dict[str, Any]:
    """RFC 7662 token introspection (S165 W2: AuthFacade-backed)."""
    del token_type_hint
    auth = get_auth_facade()
    try:
        result = await auth.verify_request(token, method="jwt")
    except Exception as exc:
        _logger.info("Introspect rejected: %s", exc)
        return {"active": False}

    if not result.is_authenticated:
        return {"active": False}

    response: dict[str, Any] = {"active": True}
    # Raw RFC 7662 fields via facade.jwt (best-effort enrichment).
    backend = auth.jwt
    if backend is not None:
        try:
            claims = await backend.decode(token)
            raw = claims.raw or {}
            for key in _INTROSPECT_FIELDS:
                value = raw.get(key)
                if value is not None:
                    response[key] = value
        except Exception:
            pass
    return response
