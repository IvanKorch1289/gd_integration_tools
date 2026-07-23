"""S175 Phase 2: SwitchProcessor (full implementation).

Split из patterns.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    run_sub_processors,
)

__all__ = ("SwitchProcessor",)


class SwitchProcessor(BaseProcessor):
    """n8n Switch node — маршрутизация по значению поля.

    Проще чем Choice: берёт значение поля из body и ищет его в cases.
    Если значение не найдено — выполняет default.

    Usage::

        .switch("status", cases={
            "pending": [SetHeaderProcessor("x-route", "pending")],
            "active": [DispatchActionProcessor("orders.process")],
        }, default=[LogProcessor()])
    """

    def __init__(
        self,
        field: str,
        cases: dict[str, list[BaseProcessor]],
        *,
        default: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"switch:{field}")
        self._field = field
        self._cases = cases
        self._default = default or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        value = None
        if isinstance(body, dict):
            value = body.get(self._field)

        key = str(value) if value is not None else ""
        branch = self._cases.get(key, self._default)
        exchange.set_property(
            "switch_matched", key if key in self._cases else "default"
        )
        await run_sub_processors(branch, exchange, context)
