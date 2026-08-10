from __future__ import annotations

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


import asyncio
from typing import TYPE_CHECKING, Protocol, cast

from fastapi import HTTPException, Request, status

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.resilience import RateLimiter

__all__ = (
    "IP_LIMIT",
    "IP_WINDOW_SECONDS",
    "TARPIT_DELAY_SECONDS",
    "USERNAME_LIMIT",
    "USERNAME_WINDOW_SECONDS",
    "check_ip_rate_limit",
    "check_username_rate_limit",
)

# === Tunables (можно вынести в config/services/login.py в S60+) ===

IP_LIMIT = 5  # attempts per window
IP_WINDOW_SECONDS = 60  # 1 min
USERNAME_LIMIT = 3  # attempts per window
USERNAME_WINDOW_SECONDS = 300  # 5 min
TARPIT_DELAY_SECONDS = 1.0  # при exceeded (tarpit)

_logger = get_logger("security.auth.ratelimit")


class _RateLimiterProvider(Protocol):
    """Callable contract for the lazy rate-limiter export."""

    def __call__(self) -> RateLimiter:
        """Return the configured limiter."""
        ...


class LoginRateLimitExceeded(HTTPException):
    """429 + Retry-After. Internal use only (subclass of HTTPException)."""

    def __init__(self, retry_after: int, identifier: str) -> None:
        """Инициализирует middleware.

:param retry_after: значение retry_after.
:param identifier: значение identifier."""
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after), "X-RateLimit-Scope": "login"},
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
    identifier: str, limit: int, window_seconds: int
) -> tuple[bool, int]:
    """Возвращает (is_ok, remaining_or_retry_after).

    Returns:
        (True, remaining) если OK;
        (False, retry_after) если exceeded.
    """
    from src.backend.core.resilience import (
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
    limiter_provider = cast(_RateLimiterProvider, get_rate_limiter)
    rate_limit_exceeded = cast(type[Exception], RateLimitExceeded)
    try:
        limiter = limiter_provider()
        result = await limiter.check(identifier, policy)
    except rate_limit_exceeded as exc:
        retry_after = getattr(exc, "retry_after", None)
        if not isinstance(retry_after, int):
            retry_after = window_seconds
        return False, retry_after
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
        identifier=f"ip:{client_ip}", limit=IP_LIMIT, window_seconds=IP_WINDOW_SECONDS
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
