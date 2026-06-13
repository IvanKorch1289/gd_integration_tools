"""R2.1 — CDC primitives ядра.

Generic ``CDCSource`` Protocol + Pydantic-модели событий.
Конкретные backend'ы (poll, listen_notify, debezium_events) — в
``src/infrastructure/cdc/`` и подключаются через factory.
"""

from src.backend.core.cdc.source import (  # noqa: F401
    CDCCursor,
    CDCEvent,
    CDCOperation,
    CDCSource,
    FakeCDCSource,
)
from src.backend.core.cdc.registry import (  # noqa: F401
    SUPPORTED_BACKENDS,
    get_cdc_source,
    is_backend_available,
    list_backends,
)

__all__ = (
    "CDCCursor",
    "CDCEvent",
    "CDCOperation",
    "CDCSource",
    "FakeCDCSource",
    "get_cdc_source",
    "is_backend_available",
    "list_backends",
    "SUPPORTED_BACKENDS",
)
