"""Protocols EIP-методы: protocol / transport / on_completion.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.builders.eip._base import EIPMixinBase

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder
    from src.backend.dsl.engine.processors import BaseProcessor

__all__ = ("ProtocolsEIPsMixin",)


class ProtocolsEIPsMixin(EIPMixinBase):
    """Transport binding (protocol/transport) + on_completion callback."""

    def protocol(self, proto: ProtocolType) -> "RouteBuilder":
        """Привязывает маршрут к конкретному протоколу (REST/SOAP/gRPC/...)."""
        self._protocol = proto
        return self  # type: ignore[return-value]

    def transport(self, config: TransportConfig) -> "RouteBuilder":
        """Настройки транспорта (endpoint, timeout, retry_count, options)."""
        self._transport_config = config
        return self  # type: ignore[return-value]

    def on_completion(
        self,
        processors: list["BaseProcessor"],
        *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
    ) -> "RouteBuilder":
        """OnCompletion — запуск callback после окончания pipeline (как finally)."""
        return cast(
            "RouteBuilder",
            self._add_lazy(  # type: ignore[attr-defined]
                "src.backend.dsl.engine.processors.eip",
                "OnCompletionProcessor",
                processors=processors,
                on_success_only=on_success_only,
                on_failure_only=on_failure_only,
            ),
        )
