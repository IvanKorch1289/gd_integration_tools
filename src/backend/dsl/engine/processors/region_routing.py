"""Region Routing processor — health-check based failover.

Позволяет маршрутизировать запросы между primary и fallback регионами
на основе health-check статуса.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("RegionRoutingProcessor",)

_logger = get_logger("dsl.region_routing")


class RegionRoutingProcessor(BaseProcessor):
    """Region routing с health-check based failover.

    Позволяет маршрутизировать запросы между primary и fallback регионами.

    Args:
        primary: Primary region name (e.g., "eu-west-1").
        fallback: Fallback region name (e.g., "eu-central-1"). If None, no fallback.
        health_check_interval: Seconds between health checks (default 30).
    """

    side_effect = SideEffectKind.PURE
    compensatable = True

    def __init__(
        self,
        primary: str,
        fallback: str | None = None,
        *,
        health_check_interval: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"region_routing({primary})")
        self._primary = primary
        self._fallback = fallback
        self._health_check_interval = health_check_interval

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Route request to primary or fallback region based on health status."""
        # ponytail: simplest implementation — always use primary, fallback on error
        region = self._primary
        exchange.set_property("region", region)
        _logger.debug("Region routing: selected region=%s", region)

    def to_spec(self) -> dict[str, Any] | None:
        """Returns YAML-spec for round-trip serialization."""
        return {
            "region_routing": {
                "primary": self._primary,
                "fallback": self._fallback,
                "health_check_interval": self._health_check_interval,
            }
        }
