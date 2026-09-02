"""Unit-тесты ``services.ai.document_parsers`` — coverage ratchet (Post-Plan A Sprint 14).

core/ai/document_parsers service package facade: re-exports 3 symbols
(SUPPORTED_MIME_TYPES frozenset, parse_document function, sniff_mime function).
~5 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable/set identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import document_parsers
from src.backend.services.ai.document_parsers import (
    SUPPORTED_MIME_TYPES,
    parse_document,
    sniff_mime,
)


@pytest.mark.unit
class TestDocumentParsersFacadeAllExports:
    """``__all__`` audit + callable/set identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["SUPPORTED_MIME_TYPES", "parse_document", "sniff_mime"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(document_parsers, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in document_parsers.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(document_parsers.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает document parsers (RAG/MCP/DSL/AIFs)."""
        assert document_parsers.__doc__ is not None
        assert "document" in document_parsers.__doc__.lower() or "parser" in document_parsers.__doc__.lower()


@pytest.mark.unit
class TestDocumentParsersFacadeIdentity:
    """Identity checks для 3 re-exports."""

    def test_supported_mime_types_is_frozenset(self) -> None:
        """``SUPPORTED_MIME_TYPES`` — frozenset of MIME strings."""
        assert isinstance(SUPPORTED_MIME_TYPES, frozenset)
        # Непустой
        assert len(SUPPORTED_MIME_TYPES) > 0

    def test_parse_document_is_callable(self) -> None:
        """``parse_document`` — callable (main entry point)."""
        assert callable(parse_document)

    def test_sniff_mime_is_callable(self) -> None:
        """``sniff_mime`` — callable (MIME sniffer)."""
        assert callable(sniff_mime)
