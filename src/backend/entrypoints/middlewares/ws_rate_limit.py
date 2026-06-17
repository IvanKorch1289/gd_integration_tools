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

Алгоритм: token-bucket via ``limits`` library (per master prompt
§0 "Single-Entry per Concern" — единый rate-limiter).

Settings (WSSettings, S164 W36):
    * ``rate_limit_per_minute`` — default 600/min per identifier.
    * ``rate_limit_burst`` — default 10 (token-bucket burst).
    * ``enabled`` — feature-flag (default ``True``).

Per-route override: route.toml::[transport.ws] rate_limit_per_minute
(реализуется в S165+ через DslService.get_route_overrides).
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from src.backend.core.config.services.websocket import ws_settings
from src.backend.core.logging import get_logger
from src.backend.entrypoints.middlewares.per_protocol_ratelimit import ws_identifier

__all__ = ("WSRateLimitMiddleware",)

logger = get_logger(__name__)


class WSRateLimitMiddleware:
    """S164 W36: ASGI middleware для WebSocket rate limiting.

    Implements token-bucket per identifier (tenant/user/IP). Configuration
    via :class:`WSSettings` (``rate_limit_per_minute``, ``rate_limit_burst``).

    Note:
        Production deployment может использовать ``limits`` library directly
        (per master prompt §0 — single-entry per concern). MVP-реализация
        — in-memory dict, sufficient для single-instance dev/CI.

        Для multi-instance production — Redis-backed bucket через
        ``core.resilience.unified_rate_limiter`` (TODO S165+).
    """

    def __init__(self, app: Any, *, enabled: bool = True) -> None:
        self.app = app
        self._enabled = enabled and ws_settings.heartbeat_interval_s > 0
        # Per-identifier bucket state.
        # Format: {identifier: (tokens: float, last_refill_ts: float)}
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (float(ws_settings.rate_limit_burst), time.monotonic())
        )

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """ASGI middleware entrypoint."""
        if not self._enabled or scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        identifier = ws_identifier(scope)
        if not self._check_rate_limit(identifier):
            logger.warning(
                "WSRateLimit: rate limit exceeded for %s",
                identifier,
            )
            # Send close frame with code 1008 (policy violation).
            await send({"type": "websocket.close", "code": 1008})
            return

        await self.app(scope, receive, send)

    def _check_rate_limit(self, identifier: str) -> bool:
        """Token-bucket check. ``True`` если request allowed, ``False`` если exceeded.

        Refill rate = ``rate_limit_per_minute / 60`` tokens/sec.
        Burst size = ``rate_limit_burst``.
        """
        now = time.monotonic()
        refill_rate = ws_settings.rate_limit_per_minute / 60.0
        burst = ws_settings.rate_limit_burst

        tokens, last_refill = self._buckets[identifier]
        # Refill: elapsed seconds * refill_rate, capped at burst.
        elapsed = now - last_refill
        new_tokens = min(burst, tokens + elapsed * refill_rate)
        if new_tokens >= 1.0:
            self._buckets[identifier] = (new_tokens - 1.0, now)
            return True
        # Rate limit exceeded.
        self._buckets[identifier] = (new_tokens, now)
        return False