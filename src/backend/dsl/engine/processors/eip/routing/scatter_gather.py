"""S63 W2 — scatter_gather.py part of routing decomp.

Classes: ScatterGatherProcessor.

ScatterGatherProcessor (fan-out + aggregate).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")


class ScatterGatherProcessor(BaseProcessor):
    """Fan-out на N маршрутов → сборка результатов.

    Отправляет копию Exchange на несколько DSL-маршрутов
    параллельно, собирает результаты в ``scatter_results``.
    """

    def __init__(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"scatter_gather({len(route_ids)})")
        self._route_ids = route_ids
        self._aggregation = aggregation
        self._timeout = timeout_seconds

    async def _call_route(
        self, route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tasks = [
            self._call_route(
                rid, exchange.in_message.body, exchange.in_message.headers, context
            )
            for rid in self._route_ids
        ]

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=self._timeout
            )
        except TimeoutError:
            exchange.fail(f"Scatter-gather timeout ({self._timeout}s)")
            return

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw_results:
            if isinstance(item, BaseException):
                errors["_exception"] = str(item)
            else:
                rid, result, error = item
                if error:
                    errors[rid] = error
                else:
                    results[rid] = result

        exchange.set_property("scatter_results", results)
        if errors:
            exchange.set_property("scatter_errors", errors)

        if self._aggregation == "merge" and results:
            merged: dict[str, Any] = {}
            for v in results.values():
                if isinstance(v, dict):
                    merged.update(v)
            exchange.set_out(body=merged, headers=dict(exchange.in_message.headers))
