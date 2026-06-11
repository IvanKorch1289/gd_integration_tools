from __future__ import annotations

"""S65 W1 — TimerProcessor extracted from components.py.

Per-processor file split.
"""

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class TimerProcessor(BaseProcessor):
    """Camel Timer Component — generates exchange events on interval or cron.

    When used as the first processor in a route, it acts as a source
    that triggers the pipeline periodically.
    """

    def __init__(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"timer({interval_seconds or cron})")
        self._interval = interval_seconds
        self._cron = cron
        self._max_fires = max_fires
        self._fire_count = 0

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        self._fire_count += 1
        exchange.set_property("timer_fire_count", self._fire_count)
        exchange.set_property("timer_fired_at", time.time())

        if self._max_fires and self._fire_count >= self._max_fires:
            exchange.set_property("timer_exhausted", True)

        if exchange.in_message.body is None:
            exchange.in_message.body = {
                "timer_fire_count": self._fire_count,
                "timestamp": time.time(),
            }
