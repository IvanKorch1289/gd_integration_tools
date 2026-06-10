"""Transport / Storage / Sink mixin для RouteBuilder.

Decomposed в S84 W2 (B1, ADR-0107 pending):
- ``sinks.py`` — 10 sink_* методов (S84 W2 B1 extraction)
- persistence / scheduling / sources / proxy / external — S85+ backlog

Backward-compat: ``from src.backend.dsl.builders.transport import TransportMixin``
работает как раньше (MRO композитный).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

from src.backend.dsl.builders.transport.external import ExternalMixin
from src.backend.dsl.builders.transport.persistence import PersistenceMixin
from src.backend.dsl.builders.transport.proxy import ProxyMixin
from src.backend.dsl.builders.transport.sinks import SinksMixin
from src.backend.dsl.builders.transport.sources import SourcesMixin


class TransportMixin(
    SourcesMixin,
    ExternalMixin,
    ProxyMixin,
    PersistenceMixin,
    SinksMixin,
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
    ) -> RouteBuilder:
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "TimerProcessor",
            interval_seconds=interval_seconds,
            cron=cron,
            max_fires=max_fires,
        )
