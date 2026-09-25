"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``dsl/engine/processors/event_store/`` — типы и хранилище.
Legacy: ``dsl/processors/event_store/processor.py`` — EventStoreProcessor
с BaseProcessor и process() (используется legacy migration tests).
"""

from src.backend.dsl.engine.processors.event_store import *  # noqa: F401,F403

from src.backend.dsl.processors.event_store.processor import (  # noqa: F401
    EventStoreProcessor as EventStoreProcessor,
)
