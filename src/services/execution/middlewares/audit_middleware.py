"""AuditMiddleware — журналирование вызовов action (W14.1.C).

Логирует:

* начало вызова (``action.dispatch.start``) с ``action_id`` и
  ``correlation_id``;
* завершение (``action.dispatch.end``) с ``success``, ``duration_ms``
  и кодом ошибки при ``success=False``.

No-op при отсутствии необязательных полей в :class:`DispatchContext`
не предусмотрен — middleware всегда логирует, но без чувствительных
данных (payload не пишется в лог).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from src.core.interfaces.action_dispatcher import (
    ActionResult,
    DispatchContext,
    MiddlewareNextHandler,
)

__all__ = ("AuditMiddleware",)

# Логгер именуется как канал «application»: реальные хендлеры
# (StreamHandler + Graylog) подключаются в composition root через
# ``LoggerManager``, а здесь — только чистый ``logging``-интерфейс,
# чтобы services-слой не зависел от ``infrastructure``.
_logger = logging.getLogger("application")


class AuditMiddleware:
    """Структурированное логирование dispatch action.

    Использует стандартный ``logging.getLogger("application")``;
    конкретные handlers (StreamHandler / Graylog) добавляются в
    composition root и применяются ко всему дереву логгеров.
    """

    async def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        next_handler: MiddlewareNextHandler,
    ) -> ActionResult:
        started_at = time.monotonic()
        extra_start = {
            "action": action,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id,
            "source": context.source,
        }
        _logger.info("action.dispatch.start", extra=extra_start)

        try:
            result = await next_handler(action, payload, context)
        except Exception:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            _logger.exception(
                "action.dispatch.error",
                extra={
                    "action": action,
                    "correlation_id": context.correlation_id,
                    "duration_ms": duration_ms,
                },
            )
            raise

        duration_ms = int((time.monotonic() - started_at) * 1000)
        extra_end: dict[str, Any] = {
            "action": action,
            "correlation_id": context.correlation_id,
            "duration_ms": duration_ms,
            "success": result.success,
        }
        if not result.success and result.error is not None:
            extra_end["error_code"] = result.error.code
        _logger.info("action.dispatch.end", extra=extra_end)
        return result
