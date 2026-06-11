from __future__ import annotations

"""S63 W2 — load_balancer.py part of routing decomp.

Classes: LoadBalancerProcessor.

LoadBalancerProcessor (round-robin / weighted).
"""

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")


class LoadBalancerProcessor(BaseProcessor):
    """Camel Load Balancer EIP — distributes exchanges across multiple routes.

    Strategies: round_robin, random, weighted, sticky (header-based).
    """

    def __init__(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"load_balancer({strategy})")
        self._targets = targets
        self._strategy = strategy
        self._weights = weights
        self._sticky_header = sticky_header
        self._rr_index = 0
        self._lock = asyncio.Lock()

    async def _select_target(self, exchange: Exchange[Any]) -> str:
        if self._strategy == "round_robin":
            async with self._lock:
                target = self._targets[self._rr_index % len(self._targets)]
                self._rr_index += 1
            return target

        if self._strategy == "random":
            import random as _random

            return _random.choice(  # noqa: S311  # load-balancing, не криптография  # non-cryptographic use
                self._targets
            )

        if self._strategy == "weighted" and self._weights:
            import random as _random

            return _random.choices(self._targets, weights=self._weights, k=1)[  # noqa: S311  # non-cryptographic use
                0
            ]  # weighted load-balancing, не криптография

        if self._strategy == "sticky" and self._sticky_header:
            key = exchange.in_message.headers.get(self._sticky_header, "")
            idx = hash(key) % len(self._targets)
            return self._targets[idx]

        return self._targets[0]

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Select a target and forward exchange via sub-pipeline executor."""
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        target = await self._select_target(exchange)
        exchange.set_property("lb_target", target)

        result, error = await SubPipelineExecutor.execute_route(
            target, exchange.in_message.body, dict(exchange.in_message.headers), context
        )
        if error:
            exchange.fail(f"Load balancer target '{target}' failed: {error}")
            return
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
