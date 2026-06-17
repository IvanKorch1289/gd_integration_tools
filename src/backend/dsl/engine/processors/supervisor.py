"""Supervisor processor — automatic restart with backoff.

Позволяет автоматически перезапускать упавшие процессы с exponential backoff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("SupervisorProcessor",)

_logger = get_logger("dsl.supervisor")


class SupervisorProcessor(BaseProcessor):
    """Supervisor pattern для fault-tolerant execution.

    Автоматически перезапускает упавшие процессы с exponential backoff.

    Args:
        max_restarts: Maximum restart attempts (default 3).
        timeout: Timeout for each restart attempt (seconds, default 60).
        backoff: Backoff multiplier between restarts (default 2.0).
    """

    side_effect = SideEffectKind.PURE
    compensatable = True

    def __init__(
        self,
        *,
        max_restarts: int = 3,
        timeout: float = 60.0,
        backoff: float = 2.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "supervisor")
        self._max_restarts = max_restarts
        self._timeout = timeout
        self._backoff = backoff

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Set supervisor parameters in exchange properties."""
        # ponytail: simplest implementation — store config in properties
        exchange.set_property("supervisor_config", {
            "max_restarts": self._max_restarts,
            "timeout": self._timeout,
            "backoff": self._backoff,
        })
        _logger.debug(
            "Supervisor configured: max_restarts=%d, timeout=%.1f, backoff=%.1f",
            self._max_restarts,
            self._timeout,
            self._backoff,
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Returns YAML-spec for round-trip serialization."""
        return {
            "supervisor": {
                "max_restarts": self._max_restarts,
                "timeout": self._timeout,
                "backoff": self._backoff,
            }
        }
