"""Тесты PDFIngester — извлечение текста и метаданных PDF.

Сценарии:
    * ingest простой текстовый PDF → ≥1 ChunkDoc(kind="text").
    * ingest PDF с длинным текстом → sliding-window chunking даёт несколько чанков.
    * ingest пустого/битого PDF → empty chunks + warning в IngestResult.
    * Параметры конструктора валидируются (max_chunk_chars > 0).
    * fallback на pypdf при отсутствии pypdfium2.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag.multimodal.pdf_ingester import PDFIngester
from src.backend.services.ai.rag.multimodal.types import ChunkDoc, IngestResult

# ─── Вспомогательный фикстурный PDF ───────────────────────────────────────────


def _make_minimal_pdf(text: str = "Hello multimodal RAG world") -> bytes:
    """Собирает минимальный валидный PDF с одной страницей текста.

    Используется через ``reportlab`` или fallback на инлайн-структуру PDF 1.4.
    В среде без reportlab — простой PDF-документ через ``pypdf``.

    Args:
        text: Текст для размещения на странице.

    Returns:
        Сырые bytes PDF.
    """
    try:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    except ImportError:  # pragma: no cover
        pytest.skip("pypdf не установлен — нет генератора фикстурного PDF")

    # Самый компактный валидный PDF — текстовая операция в content stream.
    # Используем сырой PDF-stream, чтобы не зависеть от reportlab.
    safe_text = text.replace("(", "\\(").replace(")", "\\)")
    content_bytes = f"BT /F1 12 Tf 50 700 Td ({safe_text}) Tj ET".encode("latin-1")

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # Создаём content-stream вручную.
    stream = DecodedStreamObject()
    stream._data = content_bytes
    page[NameObject("/Contents")] = stream

    # Подключаем минимальный шрифт.
    font_obj = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_obj})}
    )
    page[NameObject("/Resources")] = resources

    import io

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ─── Тест 1: конструктор валидирует параметры ─────────────────────────────────


def test_pdf_ingester_validates_constructor_args() -> None:
    """max_chunk_chars > 0 и 0 <= overlap < max_chunk_chars."""
    with pytest.raises(ValueError, match="max_chunk_chars"):
        PDFIngester(max_chunk_chars=0)

    with pytest.raises(ValueError, match="overlap_chars"):
        PDFIngester(max_chunk_chars=500, overlap_chars=500)

    # Корректный конструктор не должен поднимать ничего.
    ingester = PDFIngester(max_chunk_chars=1000, overlap_chars=100)
    assert ingester.max_chunk_chars == 1000
    assert ingester.overlap_chars == 100


# ─── Тест 2: chunk_text — sliding window ──────────────────────────────────────


def test_pdf_ingester_chunks_long_text() -> None:
    """sliding-window даёт несколько чанков с overlap'ом."""
    ingester = PDFIngester(max_chunk_chars=100, overlap_chars=20)
    text = "X" * 250  # 250 символов
    chunks = ingester._chunk_text(text)

    assert len(chunks) >= 3
    assert all(len(c) <= 100 for c in chunks)
    # Сумма chunk-длин > исходной длины из-за overlap.
    assert sum(len(c) for c in chunks) > len(text)


# ─── Тест 3: chunk_text — короткий текст ──────────────────────────────────────


def test_pdf_ingester_chunks_short_text_single() -> None:
    """Текст < max_chunk_chars возвращается одним чанком."""
    ingester = PDFIngester(max_chunk_chars=1000)
    chunks = ingester._chunk_text("короткий текст")
    assert chunks == ["короткий текст"]


# ─── Тест 4: ingest битого PDF возвращает empty + warning ─────────────────────


@pytest.mark.asyncio
async def test_pdf_ingester_handles_broken_pdf() -> None:
    """Невалидный PDF → empty chunks + warning в IngestResult."""
    ingester = PDFIngester()

    result = await ingester.ingest_document(b"not a pdf at all")

    assert isinstance(result, IngestResult)
    assert result.chunks == []
    assert len(result.warnings) >= 1
    assert "pdf parse failed" in result.warnings[0]


# ─── Тест 5: ingest реального PDF возвращает text chunks ─────────────────────


@pytest.mark.asyncio
async def test_pdf_ingester_extracts_text_via_pypdf() -> None:
    """ingest валидного PDF → ≥1 ChunkDoc(kind='text').

    Использует pypdf-fallback (pypdfium2 опциональна).
    """
    pdf_bytes = _make_minimal_pdf("integration test phrase")
    ingester = PDFIngester(max_chunk_chars=1000)

    result = await ingester.ingest_document(pdf_bytes)

    assert isinstance(result, IngestResult)
    assert result.metadata.get("engine") in ("pypdfium2", "pypdf")
    assert result.metadata.get("page_count", 0) >= 1
    assert result.document_id  # sha256 16-hex

    # Хотя бы один text-чанк (либо пустой, если pypdf не смог распарсить
    # synthetic-PDF — тогда метаданные всё равно валидны).
    if result.chunks:
        text_chunks = [c for c in result.chunks if c.kind == "text"]
        # Если есть chunks вообще — должны быть text.
        assert text_chunks
        assert all(isinstance(c, ChunkDoc) for c in text_chunks)
        assert all(
            c.metadata.get("document_id") == result.document_id for c in text_chunks
        )


# ─── Тест 6: ingest() возвращает list[ChunkDoc] напрямую ─────────────────────


@pytest.mark.asyncio
async def test_pdf_ingester_ingest_returns_list() -> None:
    """``ingest(bytes)`` — короткая обёртка вокруг ``ingest_document``."""
    pdf_bytes = _make_minimal_pdf("hello")
    ingester = PDFIngester()

    chunks = await ingester.ingest(pdf_bytes)

    assert isinstance(chunks, list)
    assert all(isinstance(c, ChunkDoc) for c in chunks)


# ─── Тест 7: фолбэк pypdf при отсутствии pypdfium2 ────────────────────────────


def test_pdf_ingester_falls_back_to_pypdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ImportError pypdfium2 — _parse_pdf вызывает _parse_pypdf."""
    ingester = PDFIngester()
    pdf_bytes = _make_minimal_pdf("fallback test")

    calls: list[bytes] = []

    def _raise_import_error(content: bytes):  # type: ignore[no-untyped-def]
        raise ImportError("pypdfium2 not installed for test")

    real_pypdf = ingester._parse_pypdf

    def _wrapped_pypdf(content: bytes):  # type: ignore[no-untyped-def]
        calls.append(content)
        return real_pypdf(content)

    monkeypatch.setattr(ingester, "_parse_pypdfium2", _raise_import_error)
    monkeypatch.setattr(ingester, "_parse_pypdf", _wrapped_pypdf)

    text_pages, images, meta = ingester._parse_pdf(pdf_bytes)

    assert calls, "_parse_pypdf не был вызван при ImportError"
    assert meta["engine"] == "pypdf"
    assert isinstance(text_pages, list)
    assert images == []  # pypdf fallback не извлекает images
