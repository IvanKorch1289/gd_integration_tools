"""Глобальный middleware обработки исключений.

Перехватывает все необработанные исключения и формирует
структурированный JSON-ответ с correlation_id для
сквозной трассировки.
"""

import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.core.errors import BaseError

__all__ = ("ExceptionHandlerMiddleware",)

logger = logging.getLogger(__name__)


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Middleware для глобальной обработки исключений.

    Поддерживает единую модель ошибок:
    - ``BaseError`` и наследники — используют ``to_dict()``
      и собственный ``status_code``.
    - Остальные исключения — оборачиваются в HTTP 500
      с traceback (только в debug-режиме).
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        """Обрабатывает запрос с перехватом исключений.

        Args:
            request: Входящий HTTP-запрос.
            call_next: Следующий обработчик.

        Returns:
            HTTP-ответ (нормальный или ошибочный).
        """
        try:
            return await call_next(request)
        except Exception as exc:
            correlation_id = getattr(request.state, "correlation_id", None)
            request_id = getattr(request.state, "request_id", None)

            if isinstance(exc, BaseError):
                error_data = exc.to_dict()
            else:
                error_message = (
                    f"{type(exc).__name__} ({exc.__class__.__module__}): {exc}"
                )
                # IL-CRIT1.4: fix `self.logger` → `logger` (module-level).
                # `BaseHTTPMiddleware` не предоставляет `self.logger`, и
                # попадание в этот branch крашилось вторичным AttributeError,
                # заслоняя первичное исключение от клиента и логов.
                traceback_str = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                logger.error(
                    "Unhandled exception: %s\n%s", error_message, traceback_str
                )
                error_data = {"message": "Internal server error", "hasErrors": True}

            if correlation_id:
                error_data["correlation_id"] = correlation_id
            if request_id:
                error_data["request_id"] = request_id

            status_code = exc.status_code if isinstance(exc, BaseError) else 500

            logger.exception(
                "Необработанное исключение [correlation_id=%s, path=%s]: %s",
                correlation_id,
                request.url.path,
                exc,
            )

            return JSONResponse(status_code=status_code, content=error_data)
