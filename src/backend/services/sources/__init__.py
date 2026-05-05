"""W23 — Сервисный слой Sources/Sinks.

Содержит:

* :mod:`registry` — :class:`SourceRegistry` / :class:`SinkRegistry`.
* :mod:`factory` — фабрики Source/Sink по YAML-spec.
* :mod:`adapter` — :class:`SourceToInvokerAdapter` (Source → Invoker).
* :mod:`idempotency` — :class:`DedupeStore` (Redis SET + cachetools).
"""

from src.services.sources.adapter import SourceToInvokerAdapter
from src.services.sources.idempotency import DedupeStore, MemoryDedupeStore
from src.services.sources.lifecycle import start_all_sources, stop_all_sources
from src.services.sources.registry import (
    SinkRegistry,
    SourceRegistry,
    get_sink_registry,
    get_source_registry,
)

__all__ = (
    "SourceRegistry",
    "SinkRegistry",
    "get_source_registry",
    "get_sink_registry",
    "SourceToInvokerAdapter",
    "DedupeStore",
    "MemoryDedupeStore",
    "start_all_sources",
    "stop_all_sources",
)
