"""Маршрутизатор парсеров: primary (markitdown) → fallback (legacy).

Wave 8.2 + Sprint S5: ``parse_document(content, mime)`` — единая точка
извлечения текста из загруженного файла. Возвращает кортеж
``(text, parse_meta)``:

* ``text`` — Markdown (при ``engine='markitdown'``) или plain-text;
* ``parse_meta`` — ``mime``, ``size_bytes``, ``warnings``, ``filename``,
  ``engine``, ``markdown`` (bool).

Поддерживаемые MIME (расширенный список Sprint S5):

* ``application/pdf``;
* ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``
  (DOCX);
* ``application/vnd.openxmlformats-officedocument.presentationml.presentation``
  (PPTX);
* ``application/vnd.openxmlformats-officedocument.spreadsheetml.sheet``
  (XLSX);
* ``text/html`` (HTML);
* ``text/csv``, ``application/json``;
* ``text/plain``, ``text/markdown``, ``application/octet-stream`` — UTF-8.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.backend.core.config.ai import markitdown_settings
from src.backend.services.ai.document_parsers._legacy import (
    _parse_docx,
    _parse_pdf,
    _parse_text,
)
from src.backend.services.ai.document_parsers._sniffer import sniff_mime

__all__ = ("SUPPORTED_MIME_TYPES", "parse_document")

logger = logging.getLogger(__name__)


SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
        "text/csv",
        "application/json",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "application/octet-stream",
    }
)


_TEXTUAL_MIMES: frozenset[str] = frozenset(
    {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}
)

# MIME, для которых markitdown — единственный путь (legacy не покрывает).
_MARKITDOWN_ONLY: frozenset[str] = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "application/json",
    }
)

# MIME, у которых есть legacy-fallback.
_LEGACY_FALLBACK: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
}


async def parse_document(
    content: bytes, mime: str, filename: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Извлекает текст + meta из загруженного документа.

    Маршрутизация (Sprint S5):

    1. plain-text MIME → UTF-8 (markitdown избыточен);
    2. иначе markitdown-engine → Markdown;
    3. при провале markitdown → legacy для PDF/DOCX/HTML; для остальных
       форматов поднимается ``ValueError``.

    Args:
        content: Сырое содержимое файла.
        mime: MIME-type из multipart-заголовка (или ``sniff_mime``).
        filename: Опциональное имя файла для аудита/sniff'инга.

    Returns:
        Кортеж ``(text, meta)``. ``meta`` содержит:
        ``mime``, ``size_bytes``, ``warnings``, ``filename``,
        ``engine`` (``markitdown`` | ``legacy``), ``markdown`` (bool).

    Raises:
        ValueError: если MIME не поддерживается, или markitdown упал
            на формате без legacy-fallback (PPTX/XLSX/CSV/JSON).
    """
    effective_mime = sniff_mime(filename, mime)
    warnings: list[str] = []

    if effective_mime in _TEXTUAL_MIMES or (
        effective_mime.startswith("text/") and effective_mime != "text/html"
    ):
        text, w = _parse_text(content)
        warnings.extend(w)
        return text, _meta(effective_mime, content, warnings, filename, "legacy", False)

    if effective_mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"MIME {effective_mime!r} не поддерживается. "
            f"Допустимы: {sorted(SUPPORTED_MIME_TYPES)}"
        )

    if markitdown_settings.engine_enabled:
        try:
            text, w = await _try_markitdown(content, effective_mime, filename)
            warnings.extend(w)
            return text, _meta(
                effective_mime, content, warnings, filename, "markitdown", True
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"markitdown failed: {exc}; fallback to legacy")
            logger.warning(
                "parse_document: markitdown упал на mime=%s: %s — fallback",
                effective_mime,
                exc,
            )

    return await _fallback_legacy(content, effective_mime, warnings, filename)


async def _try_markitdown(
    content: bytes, mime: str, filename: str | None
) -> tuple[str, list[str]]:
    """Делегирует в MarkitdownEngine; пробрасывает все исключения."""
    from src.backend.services.ai.document_parsers._markitdown import MarkitdownEngine

    engine = MarkitdownEngine()
    return await engine.convert(content, mime, filename)


async def _fallback_legacy(
    content: bytes, mime: str, warnings: list[str], filename: str | None
) -> tuple[str, dict[str, Any]]:
    """Legacy-парсинг (pypdf/docx/bs4); для markitdown-only форматов ValueError."""
    kind = _LEGACY_FALLBACK.get(mime)
    if kind == "pdf":
        text, w = await asyncio.to_thread(_parse_pdf, content)
        warnings.extend(w)
    elif kind == "docx":
        text, w = await asyncio.to_thread(_parse_docx, content)
        warnings.extend(w)
    elif kind == "html":
        text, w = await _parse_html_legacy(content)
        warnings.extend(w)
    elif mime in _MARKITDOWN_ONLY:
        raise ValueError(
            f"MIME {mime!r} требует markitdown-engine, и legacy-fallback недоступен."
        )
    else:
        text, w = _parse_text(content)
        warnings.extend(w)

    return text, _meta(mime, content, warnings, filename, "legacy", False)


async def _parse_html_legacy(content: bytes) -> tuple[str, list[str]]:
    """HTML → plain-text через BeautifulSoup (bs4 уже в core-deps)."""
    warnings: list[str] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "lxml")
        return soup.get_text(separator="\n", strip=True), warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"bs4 fallback failed: {exc}")
        return _parse_text(content)


def _meta(
    mime: str,
    content: bytes,
    warnings: list[str],
    filename: str | None,
    engine: str,
    markdown: bool,
) -> dict[str, Any]:
    """Сборка ``parse_meta`` dict (единое место для контракта)."""
    return {
        "mime": mime,
        "size_bytes": len(content),
        "warnings": warnings,
        "filename": filename,
        "engine": engine,
        "markdown": markdown,
    }
