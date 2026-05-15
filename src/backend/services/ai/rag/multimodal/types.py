"""Общие типы MultimodalRAG (``ChunkDoc``, ``IngestResult``, ``SearchResult``).

Определяет единую модель чанка документа для PDF/изображений/текста,
агрегированный результат ingest_document и пары (chunk, score) после search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ChunkKind = Literal["text", "image", "audio"]
"""Тип контента чанка — текст, изображение или аудио."""


@dataclass(slots=True)
class ChunkDoc:
    """Единица хранения мультимодального RAG (текст или бинарный контент).

    Унифицирует представление чанков PDF (страницы текста + embedded
    изображения) и отдельных изображений/аудио. Используется как input
    для embedders и как результат search.

    Attributes:
        chunk_id: Уникальный идентификатор чанка (UUID hex).
        kind: Тип контента — ``text``, ``image`` или ``audio``.
        content: Содержимое чанка (``str`` для text, ``bytes`` для image/audio).
        metadata: Произвольные метаданные (page_num, bbox, mime, source_path,
            tenant_id, collection, namespace и др.).
        embedding: Векторное представление (заполняется embedder'ом, опционально).
        embedding_kind: Идентификатор embedder'а (``clip``, ``colpali``,
            ``sentence-transformers`` и т.п.). ``None`` до вызова embed.
        timestamp: Время создания чанка (UTC).
    """

    chunk_id: str
    kind: ChunkKind
    content: str | bytes
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    embedding_kind: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class IngestResult:
    """Агрегированный результат ingest_document.

    Attributes:
        document_id: Идентификатор исходного документа (например, sha256 от path).
        chunks: Список созданных ChunkDoc.
        metadata: Метаданные документа (title, author, page_count, mime).
        warnings: Не-критичные предупреждения (например, провал OCR на странице).
    """

    document_id: str
    chunks: list[ChunkDoc]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchResult:
    """Пара ``(chunk, score)`` для результата search.

    Attributes:
        chunk: Найденный ChunkDoc.
        score: Cosine similarity (или другой метрики) в диапазоне [-1, 1].
    """

    chunk: ChunkDoc
    score: float


__all__ = (
    "ChunkDoc",
    "ChunkKind",
    "IngestResult",
    "SearchResult",
)
