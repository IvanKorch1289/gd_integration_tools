"""Watchdog — deadline-эскалация для long-running asyncio task'ов.

Лёгкая обёртка над ``asyncio.wait_for`` с логированием через
``structlog`` и сообщением в Sentry (если доступен).

Использование::

    wd = Watchdog(name="audit-replay-flush", deadline_seconds=30)
    await wd.wrap(coro_or_awaitable())

При превышении deadline Watchdog отменяет корутину и логирует
``watchdog.deadline_exceeded`` с именем задачи. Sentry-capture
выполняется через duck-typing — отсутствие ``sentry_sdk`` не падает.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

__all__ = ("Watchdog",)

_T = TypeVar("_T")
_logger = logging.getLogger(__name__)


class Watchdog:
    """Контролирует deadline для одной корутины."""

    def __init__(self, *, name: str, deadline_seconds: float) -> None:
        self.name = name
        self.deadline_seconds = deadline_seconds

    async def wrap(
        self,
        coro: Coroutine[Any, Any, _T] | Awaitable[_T],
    ) -> _T:
        """Выполняет ``coro`` с deadline-cancel'ом."""
        try:
            return await asyncio.wait_for(coro, timeout=self.deadline_seconds)
        except asyncio.TimeoutError:
            _logger.warning(
                "watchdog.deadline_exceeded",
                extra={
                    "task_name": self.name,
                    "deadline_seconds": self.deadline_seconds,
                },
            )
            self._capture_sentry()
            raise

    def _capture_sentry(self) -> None:
        try:
            import sentry_sdk
        except ImportError:
            return
        try:
            sentry_sdk.capture_message(
                f"Watchdog deadline exceeded: {self.name}",
                level="warning",
            )
        except Exception:  # noqa: BLE001
            return
