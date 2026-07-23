"""S175 Phase 2: ReturnAddressProcessor (full implementation).

Camel EIP: https://camel.apache.org/components/latest/eips/return-address.html
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)
from src.backend.dsl.engine.processors.eip.reliability._legacy import HEADER_RETURN_ADDRESS

__all__ = ("ReturnAddressProcessor", "HEADER_RETURN_ADDRESS")

_log = get_logger(__name__)


# ── ReturnAddressProcessor ──────────────────────────────────────────


class ReturnAddressProcessor(BaseProcessor):
    """Capture reply-to / return address (Camel Return Address).

    Args:
        return_address: статический endpoint URI (e.g., ``kafka:replies``,
            ``http://api.example.com/callback``).
        address_resolver: callable(exchange) → str (для dynamic address).
            Если задан — имеет приоритет над ``return_address``.
        header_name: имя header (default ``return_address``).
        name: имя процессора.

    Использование (request-reply pattern)::

        .process(ReturnAddressProcessor(
            return_address="kafka:customer-replies",
        ))
        .process(SendToProcessor(endpoint="kafka:customer-requests"))

    Downstream consumer читает ``return_address`` header для callback routing.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        return_address: str | None = None,
        *,
        address_resolver: Callable[[Exchange[Any]], str | Awaitable[str]] | None = None,
        header_name: str = HEADER_RETURN_ADDRESS,
        name: str | None = None,
    ) -> None:
        if return_address is None and address_resolver is None:
            raise ValueError(
                "ReturnAddressProcessor: either return_address or address_resolver required"
            )
        super().__init__(name=name or "return_address")
        self._static_address = return_address
        self._resolver = address_resolver
        self._header_name = header_name
        self._lock = threading.Lock()
        self._resolved_count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Capture return address для request-reply: preserve existing или resolve new."""
        # Preserve existing return address if already set (chained requests)
        existing = exchange.in_message.get_header(self._header_name)
        if existing:
            _log.debug("ReturnAddress: preserve existing %s", existing)
            return

        if self._resolver is not None:
            addr = self._resolver(exchange)
            if asyncio.iscoroutine(addr):
                addr = await addr
        else:
            addr = self._static_address

        addr_str = str(addr)
        exchange.in_message.set_header(self._header_name, addr_str)
        with self._lock:
            self._resolved_count += 1
        _log.debug("ReturnAddress: set %s", addr_str)

    def stats(self) -> dict[str, int]:
        """Возвращает счётчик resolved под lock."""
        with self._lock:
            return {"resolved": self._resolved_count}

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует конфиг процессора в JSON-Schema spec."""
        return {"type": "return_address", "return_address": self._static_address}
