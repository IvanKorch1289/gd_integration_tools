"""RAG Lineage — track source documents, chunks, embedding model for RAG responses.

v21 §2.1: RAG provenance (track source documents, versions, chunks для каждого
LLM response). OpenLineage integration через :class:`LineageEvent`.

Per-tracked fields:
* ``chunk_id`` — ID retrieval chunk
* ``source_doc_id`` — ID source document
* ``source_doc_version`` — version source document (для compliance audit)
* ``embedding_model`` — model used для chunk embedding
* ``retrieval_score`` — similarity score (для debug / quality analysis)
* ``tenant_id`` — tenant isolation (multi-tenancy compliance)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.backend.services.lineage import get_lineage_emitter

__all__ = ("RAGChunkSource", "RAGLineageTracker", "RAGResponseLineage")

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RAGChunkSource:
    """Single chunk source для RAG response.

    Attributes:
        chunk_id: ID retrieval chunk (в vector store).
        source_doc_id: ID source document.
        source_doc_version: Version source document (ISO date или git SHA).
        embedding_model: Embedding model used (``"text-embedding-3-small"``, ...).
        retrieval_score: Cosine similarity score (0.0-1.0).
    """

    chunk_id: str
    source_doc_id: str
    source_doc_version: str
    embedding_model: str
    retrieval_score: float


@dataclass(slots=True)
class RAGResponseLineage:
    """Lineage для одного RAG LLM response.

    Attributes:
        response_id: UUID LLM response.
        run_id: Pipeline run ID.
        user_query: User query (для EU AI Act audit).
        llm_model: LLM model used (``"gpt-4o"``, ``"claude-sonnet-4"``, ...).
        chunk_sources: Per-chunk source info.
        prompt_template: Template name (если используется).
        timestamp: Unix timestamp (sec).
    """

    response_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    user_query: str = ""
    llm_model: str = ""
    chunk_sources: list[RAGChunkSource] = field(default_factory=list)
    prompt_template: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_lineage_event(self, dataset: str = "rag_response") -> dict[str, Any]:
        """Serialize в LineageEvent format (compatible with DataLineageProcessor)."""
        return {
            "event_id": str(uuid.uuid4()),
            "run_id": self.run_id or self.response_id,
            "event_type": "output",
            "node": {
                "id": f"output:{dataset}:{self.response_id}",
                "type": "output",
                "name": f"{dataset}:{self.response_id}",
                "attributes": {
                    "llm_model": self.llm_model,
                    "prompt_template": self.prompt_template,
                    "chunk_count": len(self.chunk_sources),
                    "response_id": self.response_id,
                },
            },
            "parent_ids": tuple(f"chunk:{cs.chunk_id}" for cs in self.chunk_sources),
            "timestamp": self.timestamp,
            "payload": {
                "user_query": self.user_query,
                "llm_model": self.llm_model,
                "prompt_template": self.prompt_template,
                "chunks": [
                    {
                        "chunk_id": cs.chunk_id,
                        "source_doc_id": cs.source_doc_id,
                        "source_doc_version": cs.source_doc_version,
                        "embedding_model": cs.embedding_model,
                        "retrieval_score": cs.retrieval_score,
                    }
                    for cs in self.chunk_sources
                ],
            },
        }


class RAGLineageTracker:
    """High-level tracker для RAG retrieval + LLM call.

    Usage::

        tracker = RAGLineageTracker(
            run_id="run-123", user_query="What is X?",
            llm_model="gpt-4o", prompt_template="qa_v3",
        )
        tracker.add_chunk_source(
            chunk_id="c-1", source_doc_id="doc-42",
            source_doc_version="2026-01-15", embedding_model="text-embedding-3-small",
            retrieval_score=0.92,
        )
        tracker.add_chunk_source(
            chunk_id="c-2", source_doc_id="doc-43",
            source_doc_version="2026-02-01", embedding_model="text-embedding-3-small",
            retrieval_score=0.85,
        )
        tracker.emit()  # publish RAGResponseLineage к LineageEmitter
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        user_query: str = "",
        llm_model: str = "",
        prompt_template: str = "",
    ) -> None:
        self._lineage = RAGResponseLineage(
            run_id=run_id,
            user_query=user_query,
            llm_model=llm_model,
            prompt_template=prompt_template,
        )

    def add_chunk_source(
        self,
        *,
        chunk_id: str,
        source_doc_id: str,
        source_doc_version: str,
        embedding_model: str,
        retrieval_score: float,
    ) -> None:
        """Add chunk source к lineage."""
        if not (0.0 <= retrieval_score <= 1.0):
            raise ValueError(
                f"retrieval_score должен быть 0.0-1.0, получено {retrieval_score}"
            )
        self._lineage.chunk_sources.append(
            RAGChunkSource(
                chunk_id=chunk_id,
                source_doc_id=source_doc_id,
                source_doc_version=source_doc_version,
                embedding_model=embedding_model,
                retrieval_score=retrieval_score,
            )
        )

    @property
    def lineage(self) -> RAGResponseLineage:
        """Возвращает RAGResponseLineage (read-only contract)."""
        return self._lineage

    def emit(self, dataset: str = "rag_response") -> dict[str, Any]:
        """Emit lineage event к LineageEmitter (in-memory по умолчанию)."""
        event_dict = self._lineage.to_lineage_event(dataset=dataset)
        emitter = get_lineage_emitter()
        emitter(event_dict)
        _log.info(
            "RAG lineage emitted: response_id=%s chunks=%d model=%s",
            self._lineage.response_id,
            len(self._lineage.chunk_sources),
            self._lineage.llm_model,
        )
        return event_dict
