"""W23 — Сервисный слой Sources/Sinks.

Содержит:

* :mod:`registry` — :class:`SourceRegistry` / :class:`SinkRegistry`.
* :mod:`factory` — фабрики Source/Sink по YAML-spec.
* :mod:`adapter` — :class:`SourceToInvokerAdapter` (Source → Invoker).
* :mod:`idempotency` — :class:`DedupeStore` (Redis SET + cachetools).
"""

from src.backend.services.sources.adapter import SourceToInvokerAdapter  # noqa: F401 — re-export
from src.backend.services.sources.idempotency import DedupeStore, MemoryDedupeStore  # noqa: F401 — re-export
from src.backend.services.sources.lifecycle import start_all_sources, stop_all_sources  # noqa: F401 — re-export
from src.backend.services.sources.registry import (
    SinkRegistry,
    SourceRegistry,
    get_sink_registry,
    get_source_registry,
)

__all__ = (
    "DedupeStore",
    "MemoryDedupeStore",
    "SinkRegistry",
    "SourceRegistry",
    "SourceToInvokerAdapter",
    "get_sink_registry",
    "get_source_registry",
    "start_all_sources",
    "stop_all_sources",
)
