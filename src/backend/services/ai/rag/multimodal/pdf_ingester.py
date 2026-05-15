"""PDFIngester — pipeline извлечения текста и embedded images из PDF.

Использует ``pypdfium2`` (native wheels для Python 3.14, быстрее ``pypdf``).
При отсутствии pypdfium2 — fallback на ``pypdf`` (уже в base-deps).

Контракт:
    * ``ingest(pdf_path) -> list[ChunkDoc]`` — извлекает per-page text + images.
    * Текст чанкуется простым sliding-window (max_chunk_chars, overlap).
    * Изображения сохраняются как ``ChunkDoc(kind="image", content=bytes)``
      с метаданными ``{page_num, bbox, image_index, mime}``.
    * Метаданные документа (title/author/page_count) попадают в ``meta``.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.backend.services.ai.rag.multimodal.types import ChunkDoc, IngestResult

logger = logging.getLogger(__name__)

__all__ = ("PDFIngester",)

# Дефолтные параметры чанкинга текста (приближение к semantic chunker).
_DEFAULT_MAX_CHARS = 1500
_DEFAULT_OVERLAP_CHARS = 200


class PDFIngester:
    """Pipeline извлечения текста и изображений из PDF.

    Использует pypdfium2 (lazy-import) с graceful fallback на pypdf.
    Возвращает один или несколько ChunkDoc:

    * ``ChunkDoc(kind="text")`` — один на chunk (sliding window) с
      метаданными ``{page_num, source_path, chunk_index}``.
    * ``ChunkDoc(kind="image")`` — один на embedded image с
      метаданными ``{page_num, image_index, mime, bbox?}``.

    Attributes:
        max_chunk_chars: Максимум символов в text-чанке.
        overlap_chars: Перекрытие между соседними чанками.
        extract_images: Если False — изображения пропускаются (только текст).
    """

    def __init__(
        self,
        *,
        max_chunk_chars: int = _DEFAULT_MAX_CHARS,
        overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
        extract_images: bool = True,
    ) -> None:
        """Инициализирует PDFIngester с параметрами чанкинга.

        Args:
            max_chunk_chars: Верхняя граница chunk-а текста в символах.
            overlap_chars: Размер overlap между соседними чанками.
            extract_images: Извлекать ли embedded images.
        """
        if max_chunk_chars <= 0:
            raise ValueError("max_chunk_chars должен быть > 0")
        if overlap_chars < 0 or overlap_chars >= max_chunk_chars:
            raise ValueError("overlap_chars ∈ [0, max_chunk_chars)")

        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars
        self.extract_images = extract_images

    async def ingest(self, pdf_path: Path | bytes) -> list[ChunkDoc]:
        """Извлекает текст и изображения из PDF, возвращает список чанков.

        Args:
            pdf_path: Путь к PDF-файлу или сырые bytes.

        Returns:
            Список ChunkDoc с text/image чанками. Empty list при ошибке
            парсинга (warning в логе).
        """
        result = await self.ingest_document(pdf_path)
        return result.chunks

    async def ingest_document(self, pdf_path: Path | bytes) -> IngestResult:
        """Полный pipeline: meta + chunks + warnings.

        Args:
            pdf_path: Путь к PDF-файлу или сырые bytes.

        Returns:
            IngestResult с заполненными chunks, metadata, warnings.
        """
        if isinstance(pdf_path, Path):
            content = await asyncio.to_thread(pdf_path.read_bytes)
            source = str(pdf_path)
        else:
            content = pdf_path
            source = "<bytes>"

        document_id = hashlib.sha256(content).hexdigest()[:16]

        chunks: list[ChunkDoc] = []
        warnings: list[str] = []
        meta: dict[str, Any] = {"source_path": source, "size_bytes": len(content)}

        try:
            text_pages, image_blobs, doc_meta = await asyncio.to_thread(
                self._parse_pdf, content
            )
            meta.update(doc_meta)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdf parse failed: {exc}")
            logger.warning("PDFIngester: парсинг PDF упал: %s", exc)
            return IngestResult(
                document_id=document_id,
                chunks=chunks,
                metadata=meta,
                warnings=warnings,
            )

        # Текстовые чанки (per-page → sliding window)
        for page_num, text in enumerate(text_pages, start=1):
            if not text.strip():
                continue
            for chunk_idx, piece in enumerate(self._chunk_text(text)):
                chunks.append(
                    ChunkDoc(
                        chunk_id=uuid4().hex,
                        kind="text",
                        content=piece,
                        metadata={
                            "source_path": source,
                            "page_num": page_num,
                            "chunk_index": chunk_idx,
                            "document_id": document_id,
                        },
                    )
                )

        # Image чанки
        if self.extract_images:
            for img in image_blobs:
                chunks.append(
                    ChunkDoc(
                        chunk_id=uuid4().hex,
                        kind="image",
                        content=img["bytes"],
                        metadata={
                            "source_path": source,
                            "page_num": img["page_num"],
                            "image_index": img["index"],
                            "mime": img.get("mime", "image/png"),
                            "document_id": document_id,
                        },
                    )
                )

        return IngestResult(
            document_id=document_id,
            chunks=chunks,
            metadata=meta,
            warnings=warnings,
        )

    def _parse_pdf(
        self, content: bytes
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        """Парсит PDF (sync): возвращает per-page text + images + meta.

        Стратегия:
            1. Пытается pypdfium2 (быстрее, native wheels).
            2. При ImportError — fallback на pypdf (без images).

        Args:
            content: Сырые bytes PDF.

        Returns:
            Кортеж ``(text_pages, image_blobs, meta)``:
            * text_pages — список текстов по страницам.
            * image_blobs — список ``{bytes, page_num, index, mime}``.
            * meta — ``{title, author, page_count, engine}``.
        """
        try:
            return self._parse_pypdfium2(content)
        except ImportError as exc:
            logger.info("PDFIngester: pypdfium2 недоступен (%s) — fallback на pypdf", exc)
            return self._parse_pypdf(content)

    @staticmethod
    def _parse_pypdfium2(
        content: bytes,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        """Парсинг через pypdfium2 (lazy-import)."""
        import pypdfium2 as pdfium  # type: ignore[import-not-found]

        text_pages: list[str] = []
        image_blobs: list[dict[str, Any]] = []

        pdf = pdfium.PdfDocument(content)
        try:
            for page_idx, page in enumerate(pdf, start=1):
                # Извлечение текста
                textpage = page.get_textpage()
                try:
                    text_pages.append(textpage.get_text_range())
                finally:
                    textpage.close()

                # Извлечение изображений (через page objects)
                for obj_idx, obj in enumerate(page.get_objects(filter=(3,))):  # type=3=image
                    try:
                        bitmap = obj.get_bitmap(render=False)
                        pil_img = bitmap.to_pil()
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        image_blobs.append(
                            {
                                "bytes": buf.getvalue(),
                                "page_num": page_idx,
                                "index": obj_idx,
                                "mime": "image/png",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "PDFIngester: пропуск image page=%s idx=%s: %s",
                            page_idx,
                            obj_idx,
                            exc,
                        )
                page.close()

            meta_obj: dict[str, Any] = {
                "page_count": len(pdf),
                "engine": "pypdfium2",
            }
            # Метаданные документа (опционально)
            try:
                doc_meta = pdf.get_metadata_dict()
                if title := doc_meta.get("Title"):
                    meta_obj["title"] = title
                if author := doc_meta.get("Author"):
                    meta_obj["author"] = author
            except Exception as exc:  # noqa: BLE001
                logger.debug("PDFIngester: не удалось прочитать meta: %s", exc)
        finally:
            pdf.close()

        return text_pages, image_blobs, meta_obj

    @staticmethod
    def _parse_pypdf(
        content: bytes,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        """Fallback парсинг через pypdf (без image extraction)."""
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text_pages = [page.extract_text() or "" for page in reader.pages]

        meta_obj: dict[str, Any] = {
            "page_count": len(reader.pages),
            "engine": "pypdf",
        }
        if reader.metadata is not None:
            if title := reader.metadata.title:
                meta_obj["title"] = title
            if author := reader.metadata.author:
                meta_obj["author"] = author

        # pypdf не извлекает images в нашем pipeline (упрощение fallback).
        return text_pages, [], meta_obj

    def _chunk_text(self, text: str) -> list[str]:
        """Sliding-window чанкинг текста.

        Args:
            text: Исходный текст страницы.

        Returns:
            Список chunk-ов длиной ≤ ``max_chunk_chars`` с overlap'ом.
        """
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks: list[str] = []
        start = 0
        step = self.max_chunk_chars - self.overlap_chars
        while start < len(text):
            end = min(start + self.max_chunk_chars, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start += step
        return chunks
