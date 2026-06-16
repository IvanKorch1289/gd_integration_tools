"""Shared RAG dataclasses/types.

S36 tech-debt: вынесено из ``rag_augment.py`` и ``rag_service/state.py``,
чтобы разорвать circular import между ``rag_augment`` и пакетом ``rag_service``.
Этот модуль не импортирует ``rag_service``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass
class RAGCitation:
    """Структурированная ссылка на источник в augment_prompt_with_citations.

    Attributes:
        source_doc: Логическое имя источника (metadata.source → fallback
            на metadata.doc_id).
        chunk_id: Идентификатор чанка из vector store (поле ``id``).
        chunk_idx: Порядковый индекс чанка внутри документа.
        score: relevance score в [0.0..1.0].
        namespace: namespace источника (для multi-tenant retrieval).
        freshness: метка свежести (fresh/stale/expired).
        ingested_at: ISO timestamp ingest'а чанка.
    """

    source_doc: str
    chunk_id: str
    chunk_idx: int | None
    score: float
    namespace: str | None
    freshness: str | None = None
    ingested_at: str | None = None


class FreshnessLabel(StrEnum):
    """Метка свежести retrieved-чанка."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


@dataclass(slots=True)
class AugmentResult:
    """Структурированный результат RAG augment."""

    prompt: str
    citations: list[RAGCitation] = field(default_factory=list)
    used_results: int = 0
    skipped_expired: int = 0
    namespace: str | None = None
    top_k: int = 5
    freshness_distribution: dict[str, int] = field(default_factory=dict)
    worst_freshness: FreshnessLabel = FreshnessLabel.FRESH

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready форма для API/UI."""
        return {
            "prompt": self.prompt,
            "citations": [
                {
                    "source_doc": c.source_doc,
                    "doc_id": c.source_doc,
                    "chunk_id": c.chunk_id,
                    "chunk_idx": c.chunk_idx,
                    "namespace": c.namespace,
                    "score": c.score,
                    "freshness": c.freshness,
                    "ingested_at": c.ingested_at,
                }
                for c in self.citations
            ],
            "used_results": self.used_results,
            "skipped_expired": self.skipped_expired,
            "namespace": self.namespace,
            "top_k": self.top_k,
            "freshness_distribution": self.freshness_distribution,
            "worst_freshness": self.worst_freshness.value,
        }
