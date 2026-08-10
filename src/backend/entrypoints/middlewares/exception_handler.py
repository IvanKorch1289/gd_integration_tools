"""Глобальный middleware обработки исключений (cycle 51 pure ASGI).

Перехватывает все необработанные исключения и формирует
структурированный JSON-ответ с correlation_id для
сквозной трассировки.

Cycle 51: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-50 (L1 middlewares).

Cycle 51 critical: catch + send response (no-raise pattern, cycle 39).
В pure ASGI middleware должен:
1. Поймать exception в try/except (аналог BaseHTTPMiddleware).
2. Send error response через send (не return JSONResponse).
3. НЕ вызвать downstream после exception (downstream уже failed).

IL-CRIT1.4 fix сохранён: module-level ``logger`` (не ``self.logger``).
"""

from __future__ import annotations

import json
import traceback
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.errors import BaseError
from src.backend.core.logging import get_logger

__all__ = ("ExceptionHandlerMiddleware",)

logger = get_logger(__name__)


class ExceptionHandlerMiddleware:
    """Pure ASGI middleware для глобальной обработки исключений (cycle 51).

    Поддерживает единую модель ошибок:
    - ``BaseError`` и наследники — используют ``to_dict()``
      и собственный ``status_code``.
    - Остальные исключения — оборачиваются в HTTP 500
      с traceback (только в debug-режиме).
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.

        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обрабатывает запрос с перехватом исключений.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            # Cycle 51 critical: non-HTTP scope (websocket/lifespan) —
            # НЕ ловим exceptions (ASGI protocol: они пробрасываются
            # для обработки в ASGI server). Только HTTP requests.
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # Cycle 51 critical: extract state (correlation_id, request_id)
            # из ASGI scope (не из request.state).
            state = scope.get("state", {}) if "state" in scope else {}
            correlation_id = (
                state.get("correlation_id") if isinstance(state, dict) else None
            )
            request_id = (
                state.get("request_id") if isinstance(state, dict) else None
            )

            if isinstance(exc, BaseError):
                error_data = dict(exc.to_dict())
            else:
                error_message = (
                    f"{type(exc).__name__} ({exc.__class__.__module__}): {exc}"
                )
                traceback_str = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__),
                )
                # B-12 fix (cycle 34): exception envelope error_id + correlation_id + Sentry capture
                error_id = str(uuid.uuid4())
                logger.error(
                    "Unhandled exception [error_id=%s]: %s\n%s",
                    error_id,
                    error_message,
                    traceback_str,
                )
                # Capture в Sentry (если SDK установлен и инициализирован).
                try:
                    import sentry_sdk  # noqa: F401 — availability probe

                    sentry_sdk.capture_exception(exc)
                except ImportError:
                    pass
                error_data = {
                    "code": "internal_error",
                    "detail": "Internal server error",
                    "error_id": error_id,
                }
                if correlation_id:
                    error_data["correlation_id"] = correlation_id
                if request_id:
                    error_data["request_id"] = request_id

            status_code = (
                exc.status_code if isinstance(exc, BaseError) else 500
            )

            if isinstance(exc, BaseError):
                # BaseError keeps legacy shape; still propagate ids if present.
                if correlation_id:
                    error_data["correlation_id"] = correlation_id
                if request_id:
                    error_data["request_id"] = request_id
                logger.exception(
                    "Необработанное исключение [correlation_id=%s, path=%s]: %s",
                    correlation_id,
                    scope.get("path", ""),
                    exc,
                )
            else:
                logger.exception(
                    "Необработанное исключение [error_id=%s, correlation_id=%s, path=%s]: %s",
                    error_data.get("error_id"),
                    correlation_id,
                    scope.get("path", ""),
                    exc,
                )

            # Cycle 51 critical: send error response через send (no-raise,
            # cycle 39 pattern). НЕ return JSONResponse (нельзя в pure ASGI).
            await self._send_error(send, status_code=status_code, data=error_data)

    @staticmethod
    async def _send_error(send: Send, *, status_code: int, data: dict) -> None:
        """Отправляет error response через send (cycle 39/40 pattern)."""
        body_bytes = json.dumps(data).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            },
        )
        await send({"type": "http.response.body", "body": body_bytes})
