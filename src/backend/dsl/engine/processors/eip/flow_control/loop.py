"""S175 Phase 2: LoopProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = logging.getLogger(__name__)

__all__ = ("LoopProcessor",)


class LoopProcessor(BaseProcessor):
    """Camel Loop EIP — execute sub-processors N times or until condition.

    Supports fixed count, do-while (condition checked after each iteration),
    and while (condition checked before). Each iteration receives the previous
    result as input body.

    Usage::

        .loop(processors=[...], count=5)
        .loop(processors=[...], until=lambda ex: ex.in_message.body.get("done"))
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        count: int | None = None,
        until: Callable[[Exchange[Any]], bool] | None = None,
        max_iterations: int = 1000,
        copy_exchange: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"loop({count or 'until'})")
        self._processors = processors
        self._count = count
        self._until = until
        self._max_iterations = max_iterations
        self._copy = copy_exchange

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Loop: применяет sub_processors до count/until/max_iterations."""
        from src.backend.dsl.engine.processors.base import run_sub_processors

        iteration = 0
        results: list[Any] = []

        while iteration < self._max_iterations:
            if self._count is not None and iteration >= self._count:
                break

            if self._until is not None and iteration > 0:
                try:
                    if self._until(exchange):
                        break
                except Exception as exc:
                    # D-AUDIT-12901 fix (cycle 129): narrow от bare
                    # 'except Exception: _' (swallow'ил SystemExit/
                    # KeyboardInterrupt от user callback) + structured
                    # warn log. Soft-fail behavior сохранён (bad user
                    # callback → break loop, prevent crash).
                    logger.warning(
                        "LoopProcessor: _until callback raised "
                        "(exc_type=%s exc_msg=%s) — breaking loop at "
                        "iteration=%d",
                        type(exc).__name__, exc, iteration,
                    )
                    break

            exchange.set_property("loop_index", iteration)
            exchange.set_property("loop_size", self._count or -1)

            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break

            await run_sub_processors(self._processors, exchange, context)

            result = (
                exchange.out_message.body
                if exchange.out_message
                else exchange.in_message.body
            )
            results.append(result)

            if exchange.out_message:
                exchange.in_message = Message(
                    body=exchange.out_message.body,
                    headers=dict(exchange.out_message.headers),
                )
                exchange.out_message = None

            iteration += 1

        exchange.set_property("loop_count", iteration)
        exchange.set_property("loop_results", results)
