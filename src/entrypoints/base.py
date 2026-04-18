"""Base entrypoint — общий dispatch/error handling для всех протоколов."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from app.dsl.commands.registry import action_handler_registry

__all__ = ("BaseEntrypoint",)

logger = logging.getLogger(__name__)


class BaseEntrypoint(ABC):
    """Абстрактный базовый класс для всех entrypoints.

    Унифицирует:
    - dispatch через ActionHandlerRegistry
    - error handling (единый формат ошибок)
    - metrics collection (latency, success/error count)
    - correlation ID propagation
    """

    protocol: str = "unknown"

    async def dispatch(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        """Dispatches action через ActionHandlerRegistry."""
        start = time.monotonic()
        try:
            result = await action_handler_registry.dispatch(
                action, payload or {}
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug(
                "%s dispatch %s: %.1fms",
                self.protocol, action, elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "%s dispatch %s failed: %s (%.1fms)",
                self.protocol, action, exc, elapsed_ms,
            )
            raise

    def serialize_result(self, result: Any) -> Any:
        """Сериализует результат для конкретного протокола. Override в подклассах."""
        return result

    def format_error(self, exc: Exception) -> dict[str, Any]:
        """Форматирует ошибку для конкретного протокола."""
        return {
            "error": exc.__class__.__name__,
            "message": str(exc),
            "protocol": self.protocol,
        }

    @abstractmethod
    async def handle(self, *args: Any, **kwargs: Any) -> Any:
        """Точка входа для обработки запроса конкретным протоколом."""
        ...
