"""Rate limiting dependency для ``POST /auth/login`` (S59 W3).

ADR-0085 Open Item: rate limiting для login endpoint (anti-brute-force).
Реализует per-IP лимит через существующий :class:`RedisRateLimiter`
(unified_rate_limiter.py, W14.1.C).

**Design decisions**:

* **Per-IP** (5 attempts/min): анти-brute-force на один IP;
* **Username check** — отдельный вызов :func:`check_username_rate_limit`
  из endpoint (после парсинга body, см. auth_login.py);
* **Tarpit delay** (1 sec при exceeded): замедляет brute-force;
* **Logging**: каждый exceeded → warning в ``security.auth.ratelimit``;
* **Fail-secure**: если Redis недоступен, **deny** (HTTP 503) — secure default.
  Раньше был fail-open (allow при недоступности Redis) — это небезопасно.

**Headers в response**:

* ``Retry-After`` (429 only) — секунд до разблокировки.
* ``X-RateLimit-Scope: login`` — для observability.

Используется как FastAPI dependency::

    @router.post("/login", dependencies=[Depends(check_ip_rate_limit)])
    async def login(payload: LoginRequest) -> LoginResponse:
        ...
"""
from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

from fastapi import HTTPException, Request, status

__all__ = (
    "check_ip_rate_limit",
    "check_username_rate_limit",
    "IP_LIMIT",
    "IP_WINDOW_SECONDS",
    "USERNAME_LIMIT",
    "USERNAME_WINDOW_SECONDS",
    "TARPIT_DELAY_SECONDS",
)

# === Tunables (можно вынести в config/services/login.py в S60+) ===

IP_LIMIT = 5  # attempts per window
IP_WINDOW_SECONDS = 60  # 1 min
USERNAME_LIMIT = 3  # attempts per window
USERNAME_WINDOW_SECONDS = 300  # 5 min
TARPIT_DELAY_SECONDS = 1.0  # при exceeded (tarpit)

_logger = get_logger("security.auth.ratelimit")


class LoginRateLimitExceeded(HTTPException):
    """429 + Retry-After. Internal use only (subclass of HTTPException)."""

    def __init__(self, retry_after: int, identifier: str) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Retry after {retry_after}s.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Scope": "login",
            },
        )
        self.retry_after = retry_after
        self.identifier = identifier


async def _extract_client_ip(request: Request) -> str:
    """Извлекает client IP, с учётом X-Forwarded-For (за reverse proxy).

    В production за nginx/ALB — X-Forwarded-For содержит real IP.
    Без него — request.client.host (прямое соединение).
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # First IP в chain = real client
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _check_rate_limit(
    identifier: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Возвращает (is_ok, remaining_or_retry_after).

    Returns:
        (True, remaining) если OK;
        (False, retry_after) если exceeded.
    """
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimit,
        RateLimitExceeded,
        get_rate_limiter,
    )

    policy = RateLimit(
        limit=limit,
        window_seconds=window_seconds,
        key_prefix="login",
        tenant_aware=False,
    )
    try:
        limiter = get_rate_limiter()
        result = await limiter.check(identifier, policy)
    except RateLimitExceeded as exc:
        return False, int(exc.retry_after or window_seconds)
    except (ImportError, RuntimeError) as exc:
        # Redis недоступен — fail-secure (deny).
        # Раньше был fail-open (allow) — небезопасно для login endpoint.
        _logger.error(
            "rate_limit.backend_unavailable identifier=%s err=%s — DENY (fail-secure)",
            identifier,
            exc,
        )
        # 503 чтобы front мог отличить от rate limit
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limit backend unavailable. Try again later.",
            headers={"X-RateLimit-Scope": "login"},
        ) from exc

    remaining = result.get("remaining", limit) if isinstance(result, dict) else limit
    return True, int(remaining)


async def check_ip_rate_limit(request: Request) -> None:
    """FastAPI dependency: per-IP rate limit (anti-brute-force на IP-level).

    Raises:
        LoginRateLimitExceeded: 429 + Retry-After.
        HTTPException: 503 если Redis недоступен (fail-secure).
    """
    client_ip = await _extract_client_ip(request)
    is_ok, value = await _check_rate_limit(
        identifier=f"ip:{client_ip}",
        limit=IP_LIMIT,
        window_seconds=IP_WINDOW_SECONDS,
    )

    if not is_ok:
        # value = retry_after
        _logger.warning(
            "rate_limit.exceeded scope=login identifier=ip:%s retry_after=%s",
            client_ip,
            value,
        )
        # Tarpit: замедляем brute-force
        await asyncio.sleep(TARPIT_DELAY_SECONDS)
        raise LoginRateLimitExceeded(retry_after=value, identifier=client_ip)


async def check_username_rate_limit(username: str) -> None:
    """Per-username rate limit (anti-targeted attacks).

    Вызывается из endpoint ПОСЛЕ парсинга body (где username уже доступен).

    Raises:
        LoginRateLimitExceeded: 429 + Retry-After.
        HTTPException: 503 если Redis недоступен (fail-secure).
    """
    if not username:
        # Без username — per-username check не имеет смысла
        return

    is_ok, value = await _check_rate_limit(
        identifier=f"user:{username}",
        limit=USERNAME_LIMIT,
        window_seconds=USERNAME_WINDOW_SECONDS,
    )

    if not is_ok:
        _logger.warning(
            "rate_limit.exceeded scope=login identifier=user:%s retry_after=%s",
            username,
            value,
        )
        raise LoginRateLimitExceeded(retry_after=value, identifier=username)
