"""PdfExtractProcessor (M24 P2 #5, D273).

Извлечение текста из PDF (pypdf, lazy import).
Pattern (D273, Ponytail): thin wrapper, skip if pypdf not installed.
"""
from __future__ import annotations

import io

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.rpa.pdf_extract")

__all__ = ("PdfExtractProcessor",)


class PdfExtractProcessor:
    """Извлечение текста из PDF (lazy pypdf)."""

    def extract(self, data: bytes) -> str | None:
        """Извлечь текст из PDF bytes.

        Args:
            data: PDF file content.

        Returns:
            Извлеченный текст или None (если не PDF или pypdf нет).

        """
        try:
            from pypdf import PdfReader
        except ImportError:
            _logger.debug("pdf_extract.pypdf_not_installed")
            return None
        try:
            reader = PdfReader(io.BytesIO(data))
            text_parts: list[str] = []
            for page in reader.pages:
                try:
                    text_parts.append(page.extract_text() or "")
                except (AttributeError, TypeError, ValueError, RuntimeError) as page_exc:
                    # cycle-9/D-AUDIT-947: narrow exceptions + observability.
                    # AttributeError — page.extract_text API change,
                    # TypeError — wrong type, ValueError — invalid page,
                    # RuntimeError — parser failure. Bare `except Exception`
                    # маскировал unrelated runtime errors.
                    import logging
                    logging.getLogger(__name__).debug(
                        "pdf_extract.page_failed",
                        extra={"error": str(page_exc)},
                    )
                    continue
            return "\n".join(text_parts) or None
        except Exception as exc:
            _logger.warning("pdf_extract.error: %s", exc)
            return None
