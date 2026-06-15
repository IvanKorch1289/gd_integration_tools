from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass


@dataclass
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
