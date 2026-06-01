"""Protocol-контракты для MultimodalRAG.

Определяет интерфейсы embedders и ingester'ов, чтобы фасад
``MultimodalRAGService`` мог быть параметризован реализациями
(CLIP / colpali / dummy) без жёстких зависимостей.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from src.backend.services.ai.rag.multimodal.types import ChunkDoc


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Контракт embedder'а для текста и/или изображений.

    Реализации:
        * ``CLIPEmbedder`` — text+image через sentence-transformers (CLIP).
        * ``ColpaliEmbedder`` — document-level embeddings (colpali_engine).
        * Dummy/test embedders в тестах.

    Атрибут ``embedding_kind`` — короткий идентификатор реализации
    (``clip``, ``colpali``), записывается в ``ChunkDoc.embedding_kind``.
    """

    embedding_kind: str

    async def embed(self, content: str | bytes) -> list[float]:
        """Возвращает вектор-эмбеддинг контента.

        Args:
            content: Текст (``str``) или бинарное изображение (``bytes``).

        Returns:
            Список float — вектор фиксированной размерности.

        Raises:
            LazyImportError: Если ML-зависимости не установлены.
        """
        ...


@runtime_checkable
class IngesterProtocol(Protocol):
    """Контракт ingester'а для документов.

    Реализации:
        * ``PDFIngester`` — PDF → list[ChunkDoc] (текст по страницам + images).
        * ``ImageIngester`` — Image → ChunkDoc (single).
    """

    async def ingest(self, source: Path | bytes) -> list[ChunkDoc]:
        """Извлекает чанки из источника.

        Args:
            source: Путь к файлу или бинарное содержимое.

        Returns:
            Список ChunkDoc — один или несколько чанков с метаданными.
        """
        ...


__all__ = ("EmbedderProtocol", "IngesterProtocol")
