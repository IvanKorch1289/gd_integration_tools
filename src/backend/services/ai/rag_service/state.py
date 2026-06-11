from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)
from src.backend.services.ai.rag_augment import (
    AugmentResult,
    FreshnessLabel,
    build_augment_result,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

class RAGCitation:
    """Структурированная ссылка на источник в augment_prompt_with_citations.

    Attributes:
        source_doc: Логическое имя источника (metadata.source → fallback
            на metadata.doc_id).
        chunk_id: Идентификатор чанка из vector store (поле ``id``).
        chunk_idx: Порядковый индекс чанка внутри документа.
        score: relevance score в [0.0..1.0] (``1.0 - distance`` если distance
            присутствует, иначе 0.0 — fallback для метаданных без расстояния).
        namespace: namespace источника (для multi-tenant retrieval).
    """

    source_doc: str
    chunk_id: str
    chunk_idx: int | None
    score: float
    namespace: str | None
