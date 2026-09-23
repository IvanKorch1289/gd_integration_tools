"""Парсеры файлов в Markdown/plain-text для RAG/MCP/DSL/AIFs.

Пакет предоставляет единую точку извлечения структурированного текста
(Markdown — при наличии markitdown-engine; plain-text — last-resort
fallback на pypdf/python-docx).

Публичный API:

* :func:`parse_document` — конвертация ``(content, mime, filename)`` в
  ``(text, meta)``; ``meta`` содержит ``mime``, ``size_bytes``,
  ``warnings``, ``filename``, ``engine`` (``markitdown`` | ``legacy``),
  ``markdown`` (bool).
* :func:`sniff_mime` — определение MIME по расширению файла, если
  ``declared`` пуст или ``application/octet-stream``.
* :data:`SUPPORTED_MIME_TYPES` — frozenset допустимых MIME (с учётом
  markitdown расширений: PPTX, XLSX, HTML, CSV, JSON).
"""

from __future__ import annotations

from src.backend.services.ai.document_parsers._orchestrator import (
    SUPPORTED_MIME_TYPES,
    parse_document,
)
from src.backend.services.ai.document_parsers._sniffer import sniff_mime

__all__ = ("SUPPORTED_MIME_TYPES", "parse_document", "sniff_mime")
