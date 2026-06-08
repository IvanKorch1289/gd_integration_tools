"""Тонкий facade для чтения PDF: текст из файла → строка.

Wave ``[wave:s18/w0-goal-driven-sweep-5-pdf-facade]``.

Назначение: точечная вспомогательная функция там, где не нужны
multimodal-чанки PDFIngester'а (см. :mod:`src.backend.services.ai.rag.
multimodal.pdf_ingester`), а только текст «как есть» — например, для
RPA-сценариев, аудита документов, контракт-валидации.

Каскад backend'ов (тот же порядок, что в PDFIngester):

1. ``pypdfium2`` — native wheels для py3.14, быстрее pure-Python.
2. ``pypdf`` — pure-Python fallback (в base-deps проекта).
3. Если ни один не импортируется → :class:`PdfReaderUnavailable`.

Контракт::

    from src.backend.utilities.pdf_reader import read_pdf

    text = read_pdf("/path/to/contract.pdf")
"""

from __future__ import annotations

from pathlib import Path

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("PdfReaderUnavailable", "read_pdf")

_logger = get_logger("utilities.pdf_reader")

_PAGE_SEP = "\n\n"


class PdfReaderUnavailable(RuntimeError):
    """Бросается, когда ни pypdfium2, ни pypdf не доступны.

    Hint в сообщении подсказывает установку: ``pip install pypdf`` или
    ``pip install pypdfium2`` (через ``[ai-rag-multimodal]`` extras).
    """


def _read_pypdfium2(path: str) -> str:
    """Извлечь текст всех страниц через pypdfium2.

    Args:
        path: Абсолютный путь к PDF-файлу.

    Returns:
        Конкатенация текста страниц через ``\\n\\n``.
    """
    import pypdfium2 as pdfium  # type: ignore[import-not-found]

    pdf = pdfium.PdfDocument(path)
    try:
        pages_text: list[str] = []
        for page in pdf:
            textpage = page.get_textpage()
            try:
                pages_text.append(textpage.get_text_range() or "")
            finally:
                textpage.close()
            page.close()
        return _PAGE_SEP.join(pages_text)
    finally:
        pdf.close()


def _read_pypdf(path: str) -> str:
    """Fallback: pypdf reader (без OCR; работает для text-based PDF).

    Args:
        path: Абсолютный путь к PDF-файлу.

    Returns:
        Конкатенация текста страниц через ``\\n\\n``.
    """
    from pypdf import PdfReader

    reader = PdfReader(path)
    return _PAGE_SEP.join(page.extract_text() or "" for page in reader.pages)


def _read_pypdf_bytes(data: bytes) -> str:
    """Fallback: pypdf reader из bytes."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return _PAGE_SEP.join(page.extract_text() or "" for page in reader.pages)


def read_pdf(path: Path | str | bytes) -> str:
    """Прочитать текст из PDF-файла или bytes.

    Каскад: pypdfium2 → pypdf → :class:`PdfReaderUnavailable`.

    Args:
        path: Путь к PDF (Path, строка) или bytes.

    Returns:
        Полный текст документа (страницы разделены ``\\n\\n``).

    Raises:
        PdfReaderUnavailable: Если ни один backend не установлен.
        FileNotFoundError: Если файл не существует.
    """
    if isinstance(path, bytes):
        try:
            return _read_pypdf_bytes(path)
        except ImportError as exc:
            raise PdfReaderUnavailable(
                "pypdf не установлен. Установите `pypdf`."
            ) from exc

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"PDF не найден: {p}")
    target = str(p)

    try:
        return _read_pypdfium2(target)
    except ImportError as exc:
        _logger.debug("pypdfium2 недоступен (%s) — fallback на pypdf", exc)

    try:
        return _read_pypdf(target)
    except ImportError as exc:
        raise PdfReaderUnavailable(
            "Ни pypdfium2, ни pypdf не установлены. Установите "
            "`pypdf` (pure-Python) или `pypdfium2` (native, faster)."
        ) from exc
