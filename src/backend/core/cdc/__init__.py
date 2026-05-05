"""R2.1 — CDC primitives ядра.

Generic ``CDCSource`` Protocol + Pydantic-модели событий.
Конкретные backend'ы (poll, listen_notify, debezium_events) — в
``src/infrastructure/cdc/`` и подключаются через factory.
"""

from src.core.cdc.source import (
    CDCCursor,
    CDCEvent,
    CDCOperation,
    CDCSource,
    FakeCDCSource,
)

__all__ = ("CDCCursor", "CDCEvent", "CDCOperation", "CDCSource", "FakeCDCSource")
