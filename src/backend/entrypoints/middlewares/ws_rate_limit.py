"""WSRateLimitMiddleware — per-WS rate limiting (S164 W36, EP-R3 fix).

ASGI middleware для rate-limiting WebSocket-сообщений по per-tenant /
per-user / per-IP identifier (extracted via ``ws_identifier`` из
:mod:`per_protocol_ratelimit`).

Использование::

    from src.backend.entrypoints.middlewares.ws_rate_limit import (
        WSRateLimitMiddleware,
    )

    app.add_middleware(WSRateLimitMiddleware)

Идентификатор приоритета (per :func:`ws_identifier`):
    1. ``X-Tenant-ID`` header → ``ws:tenant:<id>``
    2. ``X-User-ID`` header → ``ws:user:<id>``
    3. client IP → ``ws:ip:<addr>``

Алгоритм: fixed-window via Redis INCR/EXPIRE (per master prompt
§0 "Single-Entry per Concern" — единый rate-limiter, ``unified_rate_limiter``).

S168 W11 P1-3 follow-up: миграция с in-memory token-bucket на
``RedisRateLimiter`` (multi-instance safe). Token-bucket semantics
заменены на fixed-window (60s window, ``rate_limit_per_minute`` limit).
``rate_limit_burst`` (legacy token-bucket) deprecated, оставлен
для backward-compat в settings.

Settings (WSSettings, S164 W36):
    * ``rate_limit_per_minute`` — default 600/min per identifier.
    * ``rate_limit_burst`` — DEPRECATED (legacy token-bucket, ignored).
    * ``enabled`` — feature-flag (default ``True``).

Per-route override: route.toml::[transport.ws] rate_limit_per_minute
(реализуется в S165+ через DslService.get_route_overrides).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.config.services.websocket import ws_settings
from src.backend.core.logging import get_logger
from src.backend.entrypoints.middlewares.per_protocol_ratelimit import ws_identifier
from src.backend.services.resilience.rate_limiter import (
    RateLimit,
    RateLimitExceeded,
    get_rate_limiter,
)

__all__ = ("WSRateLimitMiddleware",)

logger = get_logger(__name__)


class WSRateLimitMiddleware:
    """S164 W36: ASGI middleware для WebSocket rate limiting.

    Implements fixed-window per identifier (tenant/user/IP) via
    :class:`RedisRateLimiter`. Configuration via :class:`WSSettings`.

    S168 W11 P1-3 follow-up: multi-instance safe via Redis (atomic INCR/EXPIRE).
    Fail-open при недоступности Redis (consistent с webhook/handler.py).

    Note:
        Legacy token-bucket (in-memory) replaced by Redis fixed-window.
        Burst semantics изменились: вместо ``burst`` per-second
        допускается ``rate_limit_per_minute`` per-60s window.
    """

    def __init__(self, app: Any, *, enabled: bool = True) -> None:
        self.app = app
        self._enabled = enabled and ws_settings.heartbeat_interval_s > 0
        self._limiter = get_rate_limiter()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """ASGI middleware entrypoint."""
        if not self._enabled or scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        identifier = ws_identifier(scope)
        if not await self._check_rate_limit(identifier):
            logger.warning("WSRateLimit: rate limit exceeded for %s", identifier)
            # Send close frame with code 1008 (policy violation).
            await send({"type": "websocket.close", "code": 1008})
            return

        await self.app(scope, receive, send)

    async def _check_rate_limit(self, identifier: str) -> bool:
        """Fixed-window check via Redis. ``True`` если request allowed.

        Returns:
            True if request allowed (under rate limit), False if exceeded.
        """
        try:
            await self._limiter.check(
                identifier,
                RateLimit(
                    limit=ws_settings.rate_limit_per_minute,
                    window_seconds=60,
                    key_prefix="ws",
                ),
            )
        except RateLimitExceeded:
            return False
        except Exception as exc:
            # Fail-open: allow request if Redis unavailable (consistent with
            # webhook/handler.py pattern). Log for observability.
            logger.warning(
                "WSRateLimit: Redis failed (fail-open) for %s: %s", identifier, exc
            )
            return True
        return True
