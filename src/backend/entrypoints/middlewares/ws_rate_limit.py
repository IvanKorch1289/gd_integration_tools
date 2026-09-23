"""WebSocket rate-limit middleware over the canonical rate-limiter facade."""

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

__all__ = ("WSRateLimitMiddleware", "WebSocketRateLimitMiddleware")

_logger = get_logger("entrypoints.middlewares.ws_rate_limit")


class WebSocketRateLimitMiddleware:
    """Limit WebSocket connections by tenant, user, or client IP."""

    def __init__(self, app: Any, *, enabled: bool = True) -> None:
        """Инициализирует middleware.

        :param app: значение app.
        """
        self._app = app
        self._enabled = enabled
        self._limiter = get_rate_limiter()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self._enabled or scope.get("type") != "websocket":
            await self._app(scope, receive, send)
            return

        identifier = ws_identifier(scope)
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
            await send({"type": "websocket.close", "code": 1008})
            return
        except Exception as exc:
            # B-05 fix (cycle 33): fail-mode управляется через
            # ``settings.resilience.rate_limit_fail_mode``. ``closed``
            # (default) → закрываем WS 1008 (deny-by-default),
            # ``open`` → pass-through (legacy-режим).
            try:
                from src.backend.core.config.settings import settings

                fail_mode = settings.resilience.rate_limit_fail_mode
            except Exception as settings_exc:  # pragma: no cover
                fail_mode = "closed"
                _logger.debug(
                    "ws_rate_limit_fail_mode_unavailable error=%r; using closed",
                    settings_exc,
                )

            _logger.error(
                "ws_rate_limit_failed identifier=%s error=%r fail_mode=%s",
                identifier,
                exc,
                fail_mode,
            )
            if fail_mode == "closed":
                await send({"type": "websocket.close", "code": 1008})
                return

        await self._app(scope, receive, send)


# Backward-compatible name used by the original S164 middleware.
WSRateLimitMiddleware = WebSocketRateLimitMiddleware
