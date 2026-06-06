"""Lineage services — Data Lineage / Provenance tracking.

v21 §2.1: Data Lineage / Provenance (EU AI Act, RAG provenance, OpenLineage).
"""

from src.backend.services.lineage.lineage_emitter import (
    InMemoryLineageEmitter,
    LineageEmitterCallable,
    LineageEmitterProtocol,
    get_lineage_emitter,
    reset_lineage_emitter,
    set_lineage_emitter,
)

__all__ = (
    "InMemoryLineageEmitter",
    "LineageEmitterCallable",
    "LineageEmitterProtocol",
    "get_lineage_emitter",
    "reset_lineage_emitter",
    "set_lineage_emitter",
)
