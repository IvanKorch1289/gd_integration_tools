"""Transport / Storage / Sink mixin для RouteBuilder.

Decomposed в S84 W2 (B1, ADR-0107 pending):
- ``sinks.py`` — 10 sink_* методов (S84 W2 B1 extraction)
- persistence / scheduling / sources / proxy / external — S85+ backlog

Backward-compat: ``from src.backend.dsl.builders.transport import TransportMixin``
работает как раньше (MRO композитный).
"""

from __future__ import annotations as annotations

from typing import Self as Self

from src.backend.dsl.builders.base._protocol import (
    _RouteBuilderProtocol as _RouteBuilderProtocol,
)
from src.backend.dsl.builders.transport.external import ExternalMixin as ExternalMixin
from src.backend.dsl.builders.transport.persistence import (
    PersistenceMixin as PersistenceMixin,
)
from src.backend.dsl.builders.transport.proxy import ProxyMixin as ProxyMixin
from src.backend.dsl.builders.transport.sinks import SinksMixin as SinksMixin
from src.backend.dsl.builders.transport.sources import SourcesMixin as SourcesMixin


class TransportMixin(
    SourcesMixin,
    ExternalMixin,
    ProxyMixin,
    PersistenceMixin,
    SinksMixin,
    _RouteBuilderProtocol,
):
    """Поведенческий миксин transport / storage / sink.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. 10 ``sink_*`` методов вынесены в
    :class:`SinksMixin` (S84 W2 B1 extraction, ADR-0107). Контракт см. в ``base.py``.
    """

    __slots__ = ()

    # --- timer (scheduling, kept in __init__.py: 1 method, low LOC) ---

    def timer(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
    ) -> Self:
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "TimerProcessor",
            interval_seconds=interval_seconds,
            cron=cron,
            max_fires=max_fires,
        )
