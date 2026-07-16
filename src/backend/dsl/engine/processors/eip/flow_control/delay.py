"""S175 Phase 2: DelayProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)

__all__ = ("DelayProcessor",)


class DelayProcessor(BaseProcessor):
    """Задержка обработки на N миллисекунд или до timestamp."""

    def __init__(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"delay({delay_ms}ms)")
        self._delay_ms = delay_ms
        self._scheduled_fn = scheduled_time_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Async sleep до scheduled_time или delay_ms (whichever specified)."""

        if self._scheduled_fn is not None:
            target = self._scheduled_fn(exchange)
            now = time.time()
            if target > now:
                await asyncio.sleep(target - now)
        elif self._delay_ms is not None and self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует delay_ms в JSON-Schema spec (None для callable scheduled_time_fn)."""
        # scheduled_time_fn — callable, не сериализуется.
        if self._scheduled_fn is not None:
            return None
        return {"delay": {"delay_ms": self._delay_ms or 0}}
