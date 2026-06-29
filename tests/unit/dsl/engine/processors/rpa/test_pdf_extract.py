"""TDD: PdfExtractProcessor (M24 P2 #5, D273).

Извлечение текста из PDF (pypdf).
Pattern (D273, Ponytail): thin wrapper + skip если pypdf нет.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestPdfExtractProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.pdf_extract import (
            PdfExtractProcessor,
        )
        proc = PdfExtractProcessor()
        assert proc is not None

    def test_extract_returns_string(self) -> None:
        """extract() возвращает string (или None если не PDF)."""
        from src.backend.dsl.engine.processors.rpa.pdf_extract import (
            PdfExtractProcessor,
        )
        proc = PdfExtractProcessor()
        # Mock bytes
        result = proc.extract(b"%PDF-1.4\n%fake content")
        # Может быть None (no real PDF) или string — просто не должно падать
        assert result is None or isinstance(result, str)
