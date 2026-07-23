"""S175 Phase 2: OnCompletionProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
)

_camel_logger = get_logger("dsl.camel")

__all__ = ("OnCompletionProcessor",)


class OnCompletionProcessor(BaseProcessor):
    """Camel OnCompletion EIP — execute callback processors after pipeline completes.

    Runs regardless of success or failure (like finally).
    Can be filtered to run only on success or only on failure.

    Usage::

        .on_completion(
            processors=[LogProcessor(), NotifyProcessor(...)],
            on_failure_only=True,
        )
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "on_completion")
        self._processors = processors
        self._on_success = on_success_only
        self._on_failure = on_failure_only

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """OnCompletion: run sub_processors по success/failure filter."""
        is_failed = exchange.status == ExchangeStatus.failed

        if self._on_success and is_failed:
            return
        if self._on_failure and not is_failed:
            return

        saved_status = exchange.status
        saved_error = exchange.error

        for proc in self._processors:
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                _camel_logger.warning("OnCompletion processor error: %s", exc)

        exchange.status = saved_status
        exchange.error = saved_error
