"""MultimodalRAGService — фасад над PDF/Image ingester'ами + embedders + store.

Контракт:
    * ``ingest_document(path, collection)`` — диспетчер по MIME (PDF | image)
      на ``PDFIngester`` / ``ImageIngester``; возвращает ``IngestResult``.
    * ``search(query, collection, top_k)`` — semantic retrieval по
      cosine similarity (in-memory store; production — Qdrant/ES).

Класс наследует legacy-методы (``ingest_text/image/audio`` + ``retrieve``)
из ``_legacy.MultimodalRAGService`` для обратной совместимости с
тестами scaffold-версии.
"""

from __future__ import annotations

import logging
import math
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.backend.core.di import app_state_singleton
from src.backend.services.ai.rag.multimodal._legacy import (
    MultimodalRAGService as _LegacyMultimodalRAGService,
)
from src.backend.services.ai.rag.multimodal._legacy import _dummy_embedding
from src.backend.services.ai.rag.multimodal.image_ingester import ImageIngester
from src.backend.services.ai.rag.multimodal.pdf_ingester import PDFIngester
from src.backend.services.ai.rag.multimodal.types import (
    ChunkDoc,
    IngestResult,
    SearchResult,
)

logger = logging.getLogger(__name__)

__all__ = (
    "MultimodalRAGService",
    "get_multimodal_rag",
)


def _cosine(a: list[float], b: list[float]) -> float:
    """Косинусное сходство двух векторов одной размерности.

    Args:
        a: Первый вектор.
        b: Второй вектор.

    Returns:
        Значение cosine similarity в диапазоне [-1, 1]; 0 при нулевой норме.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class MultimodalRAGService(_LegacyMultimodalRAGService):
    """Объединённый фасад MultimodalRAG (PDF/image + legacy scaffold).

    Расширяет scaffold (``_LegacyMultimodalRAGService``) новыми методами:

    * ``ingest_document(path, collection)`` — PDF/image pipeline →
      embeddings → store с группировкой по collection.
    * ``search(query, collection, top_k)`` — cosine retrieval; query может
      быть текстом или image bytes.

    In-memory store: словарь ``collection → {chunk_id → ChunkDoc}``.
    Embedder задаётся через ``set_embedder`` (по умолчанию — dummy
    sha-based из legacy scaffold для безопасной работы без ML-deps).

    Attributes:
        _collections: Map ``collection_name → dict[chunk_id, ChunkDoc]``.
        _embedder: Активный embedder (``EmbedderProtocol`` или None).
        _pdf_ingester: Дефолтный PDFIngester (lazy-init).
        _image_ingester: Дефолтный ImageIngester (lazy-init).
    """

    def __init__(self) -> None:
        """Инициализирует пустой store и дефолтные ingester'ы."""
        super().__init__()
        self._collections: dict[str, dict[str, ChunkDoc]] = {}
        self._embedder: Any | None = None
        self._pdf_ingester = PDFIngester()
        self._image_ingester = ImageIngester()

    def set_embedder(self, embedder: Any) -> None:
        """Назначает кастомный embedder (CLIP / colpali / dummy).

        Args:
            embedder: Объект с ``async embed(content) -> list[float]`` и
                атрибутом ``embedding_kind: str``.
        """
        self._embedder = embedder

    def set_pdf_ingester(self, ingester: PDFIngester) -> None:
        """Заменяет дефолтный PDFIngester (например, с custom chunk size)."""
        self._pdf_ingester = ingester

    def set_image_ingester(self, ingester: ImageIngester) -> None:
        """Заменяет дефолтный ImageIngester."""
        self._image_ingester = ingester

    async def ingest_document(
        self,
        path: Path | bytes,
        collection: str = "default",
        *,
        mime: str | None = None,
    ) -> IngestResult:
        """Ingestion документа: диспетчер по MIME на нужный ingester.

        Поддерживаемые MIME:
            * ``application/pdf`` → PDFIngester.
            * ``image/*`` → ImageIngester.

        Args:
            path: Путь к файлу или bytes (тогда ``mime`` обязателен).
            collection: Имя коллекции (namespace) для хранения чанков.
            mime: Опциональный MIME-override; иначе sniff по расширению.

        Returns:
            IngestResult с chunks, metadata, warnings.

        Raises:
            ValueError: Если MIME не поддерживается или не определён.
        """
        effective_mime = self._resolve_mime(path, mime)

        result: IngestResult
        match effective_mime:
            case "application/pdf":
                result = await self._pdf_ingester.ingest_document(path)
            case m if m.startswith("image/"):
                chunk = await self._image_ingester.ingest(path)
                result = IngestResult(
                    document_id=chunk.metadata.get("sha256") or uuid4().hex,
                    chunks=[chunk],
                    metadata={"mime": m, "source_path": chunk.metadata.get("source_path")},
                )
            case other:
                raise ValueError(
                    f"MultimodalRAGService.ingest_document: MIME {other!r} "
                    "не поддерживается (PDF/image)."
                )

        # Embed + store, только если feature-flag активен
        if not self._is_enabled():
            return result

        bucket = self._collections.setdefault(collection, {})
        for chunk in result.chunks:
            if chunk.embedding is None:
                chunk.embedding = await self._embed_safe(chunk.content)
                if self._embedder is not None:
                    chunk.embedding_kind = self._embedder.embedding_kind
                else:
                    chunk.embedding_kind = chunk.embedding_kind or "dummy"
            chunk.metadata["collection"] = collection
            bucket[chunk.chunk_id] = chunk

        return result

    async def search(
        self,
        query: str | bytes,
        collection: str = "default",
        top_k: int = 10,
    ) -> list[SearchResult]:
        """Semantic search по embeddings (cosine similarity).

        Args:
            query: Текст или image bytes.
            collection: Имя коллекции для поиска.
            top_k: Максимум возвращаемых результатов.

        Returns:
            Отсортированный по score список SearchResult.
        """
        if not self._is_enabled():
            return []

        bucket = self._collections.get(collection)
        if not bucket:
            return []

        query_vec = await self._embed_safe(query)

        scored: list[SearchResult] = []
        for chunk in bucket.values():
            if chunk.embedding is None:
                continue
            score = _cosine(chunk.embedding, query_vec)
            scored.append(SearchResult(chunk=chunk, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def delete_collection(self, collection: str) -> int:
        """Удаляет коллекцию целиком, возвращает количество удалённых чанков.

        Args:
            collection: Имя коллекции.

        Returns:
            Число удалённых ChunkDoc; 0 если коллекция отсутствовала.
        """
        bucket = self._collections.pop(collection, {})
        return len(bucket)

    async def _embed_safe(self, content: str | bytes) -> list[float]:
        """Возвращает embedding через self._embedder или dummy fallback.

        Args:
            content: Текст или bytes.

        Returns:
            Список float — реальный embedding или sha-based dummy.
        """
        if self._embedder is None:
            return _dummy_embedding(content)
        try:
            return await self._embedder.embed(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MultimodalRAGService: embedder упал (%s) — fallback на dummy",
                exc,
            )
            return _dummy_embedding(content)

    @staticmethod
    def _resolve_mime(source: Path | bytes, override: str | None) -> str:
        """Определяет MIME из пути или override.

        Args:
            source: Path или bytes.
            override: Явный MIME (приоритетный).

        Returns:
            MIME-строка (``application/pdf``, ``image/png`` и т.п.).

        Raises:
            ValueError: Если source — bytes и override не задан.
        """
        if override:
            return override.lower()
        if isinstance(source, Path):
            guessed, _ = mimetypes.guess_type(source.name)
            if guessed:
                return guessed
            # Sniff по магическим байтам (минимальный набор)
            head = source.read_bytes()[:8] if source.is_file() else b""
            if head.startswith(b"%PDF-"):
                return "application/pdf"
            if head.startswith(b"\x89PNG"):
                return "image/png"
            if head.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"
            raise ValueError(
                f"MultimodalRAGService: не удалось определить MIME для {source!r}"
            )
        raise ValueError(
            "MultimodalRAGService: для bytes-source требуется явный аргумент mime."
        )


@app_state_singleton("multimodal_rag", factory=MultimodalRAGService)
def get_multimodal_rag() -> MultimodalRAGService:
    """Возвращает singleton ``MultimodalRAGService`` через DI.

    Returns:
        Экземпляр MultimodalRAGService, зарегистрированный в app_state.
    """
    ...
