"""S175 Phase 2: ForEachProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
)

__all__ = ("ForEachProcessor",)


class ForEachProcessor(BaseProcessor):
    """For-Each EIP — iterate over a collection, executing sub-processors for each item.

    Uses JMESPath expression to extract the iterable from the exchange body.
    Each iteration sets exchange.in_message.body to the current item and runs
    the sub-processors. Results are collected in exchange.properties.

    Usage::

        .for_each(items_path="data.items", processors=[LogProcessor(), TransformProcessor(...)])
    """

    def __init__(
        self,
        items_path: str,
        processors: list[BaseProcessor],
        *,
        copy_exchange: bool = True,
        max_iterations: int = 10000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"for_each({items_path})")
        self._items_path = items_path
        self._processors = processors
        self._copy = copy_exchange
        self._max_iterations = max_iterations

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """ForEach: extract items via JMESPath, apply sub_processors per item."""
        import jmespath

        from src.backend.dsl.engine.processors.base import run_sub_processors

        # Extract iterable from exchange body using JMESPath
        items = jmespath.search(self._items_path, exchange.in_message.body)
        if items is None:
            items = []

        # Ensure items is a list
        if not isinstance(items, list):
            items = [items]

        results: list[Any] = []
        iteration = 0

        # Store original in_message for restoration if needed
        original_in_message = exchange.in_message

        for item in items:
            if iteration >= self._max_iterations:
                break

            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break

            # Set the current item as the exchange body
            if self._copy:
                # Create a copy of the exchange for this iteration
                exchange.in_message = Message(
                    body=item, headers=dict(exchange.in_message.headers)
                )
            else:
                # Modify in place
                exchange.in_message.body = item

            exchange.set_property("for_each_index", iteration)

            # Run sub-processors
            await run_sub_processors(self._processors, exchange, context)

            # Collect result
            result = (
                exchange.out_message.body
                if exchange.out_message
                else exchange.in_message.body
            )
            results.append(result)

            # Prepare for next iteration - move out to in if present
            if exchange.out_message:
                exchange.in_message = Message(
                    body=exchange.out_message.body,
                    headers=dict(exchange.out_message.headers),
                )
                exchange.out_message = None

            iteration += 1

        # Restore original in_message
        exchange.in_message = original_in_message

        # Set properties with results
        exchange.set_property("for_each_results", results)
        exchange.set_property("for_each_count", iteration)
