from __future__ import annotations
"""S65 W1 — PollingConsumerProcessor extracted from components.py.

Per-processor file split.
"""

import contextlib
from collections.abc import Callable
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor


_comp_logger = get_logger("dsl.components")




class PollingConsumerProcessor(BaseProcessor):
    """Camel Polling Consumer — periodically calls an action and feeds results into pipeline."""

    def __init__(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        filter_fn: Callable[[Any], bool] | None = None,
        result_property: str = "polled_data",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"poll:{source_action}")
        self._action = source_action
        self._payload = payload or {}
        self._filter_fn = filter_fn
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.schemas.invocation import ActionCommandSchema

        command = ActionCommandSchema(action=self._action, payload=self._payload)
        try:
            result = await context.action_registry.dispatch(command)
        except (KeyError, Exception) as exc:
            exchange.fail(f"Polling action '{self._action}' failed: {exc}")
            return

        if self._filter_fn and isinstance(result, list):
            result = [item for item in result if self._filter_fn(item)]

        exchange.set_property(self._result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
