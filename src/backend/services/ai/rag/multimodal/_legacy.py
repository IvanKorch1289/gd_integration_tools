"""MultimodalRAG legacy scaffold — dummy-embedding фолбэк.

Содержит scaffold-версию ``MultimodalRAGService`` (PLAN V18, Sprint 5)
с dummy 384-dim sha-embeddings и in-memory store. K4 W1 расширил
функционал через ``service.MultimodalRAGService`` (наследует этот класс
и добавляет ``ingest_document`` / ``search``).

Ограничения этого слоя:
    - Embeddings — dummy 384-dim вектора (без ML-зависимостей).
    - Хранилище — in-memory (без persistence).
    - Feature-flag ``multimodal_rag_enabled`` управляет активацией;
      при False все ingest/retrieve не выполняются (empty list / noop).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

if TYPE_CHECKING:
    pass

__all__ = ("MultimodalEntry", "MultimodalRAGService")

# Размерность placeholder-эмбеддингов (имитирует sentence-transformers 384-dim)
_EMBEDDING_DIM = 384


def _dummy_embedding(source: bytes | str) -> list[float]:
    """Генерирует детерминированный dummy 384-dim вектор по содержимому.

    Используется только для unit-тестов без ML-зависимостей.
    В production заменяется на реальный embedder (CLIP / BGE-M3 / Whisper+text).

    Args:
        source: Входной контент — строка или байты.

    Returns:
        Список из 384 float в диапазоне [-1, 1].
    """
    raw: bytes = source.encode("utf-8") if isinstance(source, str) else source
    digest = hashlib.sha256(raw).digest()
    # Расширяем 32 байта SHA-256 до 384 float повторением и масштабированием
    repeated = (digest * math.ceil(_EMBEDDING_DIM / len(digest)))[:_EMBEDDING_DIM]
    return [(b / 127.5) - 1.0 for b in repeated]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Вычисляет косинусное сходство двух векторов.

    Args:
        a: Первый вектор.
        b: Второй вектор.

    Returns:
        Значение cosine similarity в диапазоне [-1, 1].
    """
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class MultimodalEntry:
    """Единица хранения мультимодального RAG.

    Attributes:
        entry_id: Уникальный идентификатор записи (UUID).
        modality: Тип модальности — ``text``, ``image`` или ``audio``.
        content: Исходное содержимое (str для text, bytes для image/audio).
        embedding: Векторное представление (384-dim placeholder).
        metadata: Произвольные метаданные (namespace, source, tenant и др.).
        timestamp: Время создания записи (UTC).
    """

    entry_id: str
    modality: Literal["text", "image", "audio"]
    content: bytes | str
    embedding: list[float]
    metadata: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class MultimodalRAGService:
    """Мультимодальный RAG-сервис (text + image + audio).

    Поддерживает ingestion контента трёх модальностей и семантический
    retrieval по query с опциональной фильтрацией по modality.

    В текущей версии (scaffold):
    - Embeddings: dummy 384-dim (без ML-библиотек).
    - Store: in-memory dict (без persistence).
    - Feature-gate: при ``multimodal_rag_enabled=False`` возвращает пустые
      результаты и не записывает в store.

    Production-расширение (Sprint 5):
    - Text embedder: BGE-M3 / sentence-transformers через lazy-import.
    - Image embedder: CLIP через lazy-import.
    - Audio embedder: Whisper → text-embedding через lazy-import.
    - Store: Qdrant / Elasticsearch vector store.

    Attributes:
        _store: Словарь entry_id → MultimodalEntry.
    """

    def __init__(self) -> None:
        """Инициализирует in-memory store."""
        self._store: dict[str, MultimodalEntry] = {}

    def _is_enabled(self) -> bool:
        """Проверяет, активирован ли feature-flag multimodal_rag_enabled.

        Returns:
            True, если сервис разрешён в текущем окружении.
        """
        from src.backend.core.config.features import feature_flags

        return feature_flags.multimodal_rag_enabled

    async def ingest_text(
        self, content: str, metadata: dict[str, Any] | None = None
    ) -> MultimodalEntry:
        """Добавляет текстовый документ в multimodal store.

        При отключённом feature-flag возвращает entry без записи в store.

        Args:
            content: Текстовое содержимое.
            metadata: Произвольные метаданные.

        Returns:
            MultimodalEntry с заполненным embedding.
        """
        entry = MultimodalEntry(
            entry_id=str(uuid4()),
            modality="text",
            content=content,
            embedding=_dummy_embedding(content),
            metadata=metadata or {},
        )
        if self._is_enabled():
            self._store[entry.entry_id] = entry
        return entry

    async def ingest_image(
        self, content: bytes, metadata: dict[str, Any] | None = None
    ) -> MultimodalEntry:
        """Добавляет изображение в multimodal store.

        В production заменяется на CLIP-embedder (lazy-import).
        При отключённом feature-flag возвращает entry без записи в store.

        Args:
            content: Бинарное содержимое изображения (PNG/JPEG/WebP и др.).
            metadata: Произвольные метаданные (filename, mime_type и т.п.).

        Returns:
            MultimodalEntry с заполненным dummy embedding.
        """
        entry = MultimodalEntry(
            entry_id=str(uuid4()),
            modality="image",
            content=content,
            embedding=_dummy_embedding(content),
            metadata=metadata or {},
        )
        if self._is_enabled():
            self._store[entry.entry_id] = entry
        return entry

    async def ingest_audio(
        self, content: bytes, metadata: dict[str, Any] | None = None
    ) -> MultimodalEntry:
        """Добавляет аудиофайл в multimodal store.

        В production: Whisper транскрибирует аудио → text-embedding.
        При отключённом feature-flag возвращает entry без записи в store.

        Args:
            content: Бинарное содержимое аудиофайла (WAV/MP3/OGG и др.).
            metadata: Произвольные метаданные (duration_s, codec и т.п.).

        Returns:
            MultimodalEntry с заполненным dummy embedding.
        """
        entry = MultimodalEntry(
            entry_id=str(uuid4()),
            modality="audio",
            content=content,
            embedding=_dummy_embedding(content),
            metadata=metadata or {},
        )
        if self._is_enabled():
            self._store[entry.entry_id] = entry
        return entry

    async def retrieve(
        self,
        query: str | bytes,
        modality_filter: list[str] | None = None,
        top_k: int = 10,
    ) -> list[MultimodalEntry]:
        """Возвращает top-K записей, наиболее близких к query.

        При отключённом feature-flag возвращает пустой список.

        Args:
            query: Строка (text) или байты (image/audio).
            modality_filter: Список модальностей для ограничения поиска
                (например, ``["text", "image"]``). При None — поиск по всем.
            top_k: Максимальное количество возвращаемых записей.

        Returns:
            Список MultimodalEntry, упорядоченный по убыванию cosine similarity.
        """
        if not self._is_enabled():
            return []

        query_embedding = _dummy_embedding(query)

        candidates = (
            entry
            for entry in self._store.values()
            if modality_filter is None or entry.modality in modality_filter
        )

        scored = sorted(
            candidates,
            key=lambda e: _cosine_similarity(e.embedding, query_embedding),
            reverse=True,
        )
        return scored[:top_k]
