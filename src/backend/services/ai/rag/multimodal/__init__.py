"""Пакет MultimodalRAG — text/image/PDF/audio embeddings и retrieval.

Структура (K4 W1):
    * ``_legacy.py`` — scaffold-версия (dummy embeddings, in-memory store).
    * ``types.py`` — общие типы (``ChunkDoc``, ``IngestResult``, ``SearchResult``).
    * ``protocols.py`` — Protocol-контракты (``EmbedderProtocol``, ``IngesterProtocol``).
    * ``pdf_ingester.py`` — PDF→chunks (текст + embedded images) через pypdfium2.
    * ``image_ingester.py`` — Image→ChunkDoc через Pillow (+ EXIF + optional VLM caption).
    * ``embedders.py`` — CLIPEmbedder (sentence-transformers) и ColpaliEmbedder (lazy).
    * ``service.py`` — фасад ``MultimodalRAGService`` (ingest_document + search).

Публичный API:
    * ``MultimodalRAGService`` — основной фасад (ingest_document/search + legacy
      ingest_text/image/audio/retrieve).
    * ``MultimodalEntry`` — единица хранения (back-compat scaffold).
    * ``ChunkDoc`` — текстовый/бинарный чанк документа с метаданными.
    * ``IngestResult`` — агрегированный результат ingest_document.
    * ``SearchResult`` — пара (chunk, score) после search.
    * ``PDFIngester`` — pipeline извлечения текста+изображений из PDF.
    * ``ImageIngester`` — pipeline для отдельных изображений.
    * ``CLIPEmbedder`` / ``ColpaliEmbedder`` — реализации embedders.
    * ``get_multimodal_rag`` — DI-singleton фасада.
"""

from __future__ import annotations

from src.backend.services.ai.rag.multimodal._legacy import MultimodalEntry
from src.backend.services.ai.rag.multimodal.embedders import (
    CLIPEmbedder,
    ColpaliEmbedder,
    LazyImportError,
)
from src.backend.services.ai.rag.multimodal.image_ingester import ImageIngester
from src.backend.services.ai.rag.multimodal.pdf_ingester import PDFIngester
from src.backend.services.ai.rag.multimodal.service import (
    MultimodalRAGService,
    get_multimodal_rag,
)
from src.backend.services.ai.rag.multimodal.types import (
    ChunkDoc,
    IngestResult,
    SearchResult,
)

__all__ = (
    "CLIPEmbedder",
    "ChunkDoc",
    "ColpaliEmbedder",
    "ImageIngester",
    "IngestResult",
    "LazyImportError",
    "MultimodalEntry",
    "MultimodalRAGService",
    "PDFIngester",
    "SearchResult",
    "get_multimodal_rag",
)
