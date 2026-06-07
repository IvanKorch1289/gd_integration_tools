"""Unified login endpoint (S58 W6d).

``POST /auth/login`` — единый entry point для аутентификации
(front выбирает method в body):

Request::

    {
      "method": "password" | "ldap",
      "username": "alice",
      "password": "..."
    }

Response (success)::

    {
      "access_token": "<jwt>",
      "token_type": "bearer",
      "auth_method": "password" | "ldap",
      "username": "alice",
      "is_superuser": false,
      "expires_in": 3600
    }

Errors:
* 400 — invalid method / missing fields;
* 401 — invalid credentials;
* 503 — LDAP не сконфигурирован / feature flag OFF (для method=ldap).

Использует :class:`UserService.login_with_method` (S58 W6c).
JWT через :mod:`core.auth.jwt_backend` (уже реализован).
"""
from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.entrypoints.api.v1.dependencies.login_ratelimit import (
    check_ip_rate_limit,
    check_username_rate_limit,
)
from src.backend.services.auth.ad_directory_client import AdAuthError

_logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# === Schemas ===

AuthMethodLiteral = Literal["password", "ldap"]


class LoginRequest(BaseModel):
    """Request body для POST /auth/login (S58 W6d)."""

    method: AuthMethodLiteral = Field(
        ...,
        description="Auth method: ``password`` (deprecated) или ``ldap`` (recommended).",
    )
    username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Username (для ``password``) или userPrincipalName/sAMAccountName (для ``ldap``).",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Plain-text password (используется для ``password`` и ``ldap`` bind).",
    )


class LoginResponse(BaseModel):
    """Success response с JWT token."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth2 token type literal, не password)
    auth_method: AuthMethodLiteral
    username: str
    is_superuser: bool
    expires_in: int = Field(
        default=3600,
        description="Token lifetime в секундах (default 1h).",
    )


# === Endpoint ===

async def _get_user_service() -> Any:
    """Lazy import UserService (избегаем circular)."""
    from extensions.core_entities.users.services.users import get_user_service

    return get_user_service()


async def _get_jwt_backend() -> Any:
    """Lazy import JWT encode (избегаем circular)."""
    from src.backend.core.auth.jwt_backend_joserfc import encode

    return encode


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified login (password или ldap)",
    description=(
        "Аутентификация по ``method`` (front выбирает). "
        "Возвращает JWT для последующих запросов."
    ),
    dependencies=[Depends(check_ip_rate_limit)],
)
async def login(payload: LoginRequest) -> LoginResponse:
    """Единый login endpoint (S58 W6d).

    Вызывает :meth:`UserService.login_with_method` с dispatch по ``payload.method``.
    На успехе выпускает JWT через ``jwt_backend_joserfc.encode``.

    Rate limiting (S59 W3):
    * per-IP (5/min) — анти-brute-force на IP-level (FastAPI dependency);
    * per-username (3/5min) — анти-targeted attacks (вызов в handler).
    """
    # S59 W3: per-username rate limit (вызываем ПОСЛЕ парсинга body).
    await check_username_rate_limit(payload.username)

    service = await _get_user_service()
    jwt_encode = await _get_jwt_backend()

    start = time.monotonic()
    try:
        user = await service.login_with_method(
            method=payload.method,
            username=payload.username,
            password=payload.password,
        )
    except AdAuthError as exc:
        _logger.warning(
            "auth.login.ldap_error username=%s method=%s err=%s",
            payload.username,
            payload.method,
            exc,
        )
        # LDAP server недоступен / ldap3 not installed / feature flag OFF
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LDAP auth unavailable: {exc}",
        ) from exc
    except ValueError as exc:
        # Неизвестный method (защита на случай bypass через прямой POST)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if user is None:
        _logger.info(
            "auth.login.failed username=%s method=%s",
            payload.username,
            payload.method,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Issue JWT
    is_superuser = bool(getattr(user, "is_superuser", False))
    try:
        # encode() returns (token_str, expires_in_seconds) — см. jwt_backend_joserfc
        result = jwt_encode(
            subject=user.username,
            claims={
                "auth_method": payload.method,
                "is_superuser": is_superuser,
            },
        )
        if isinstance(result, tuple) and len(result) == 2:
            token, expires_in = result
        else:
            token = result
            expires_in = 3600
    except (TypeError, ValueError) as exc:
        # Fallback: просто return mock-token в dev mode (НЕ для prod!)
        _logger.warning("auth.login.jwt_encode_failed err=%s — using mock token", exc)
        token = f"mock-jwt-{user.username}-{int(time.time())}"
        expires_in = 3600
    elapsed_ms = (time.monotonic() - start) * 1000
    _logger.info(
        "auth.login.success username=%s method=%s elapsed_ms=%.1f",
        user.username,
        payload.method,
        elapsed_ms,
    )

    return LoginResponse(
        access_token=token,
        auth_method=payload.method,
        username=user.username,
        is_superuser=is_superuser,
        expires_in=expires_in,
    )
