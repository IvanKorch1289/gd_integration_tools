"""Тесты orchestrator-router: маршрутизация markitdown ↔ legacy."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.services.ai.document_parsers import (
    SUPPORTED_MIME_TYPES,
    parse_document,
)


class TestPlainTextRoute:
    """plain-text — markitdown не вызывается, engine=legacy."""

    async def test_text_plain_returns_decoded(self) -> None:
        text, meta = await parse_document(b"hello", "text/plain", "a.txt")
        assert text == "hello"
        assert meta["engine"] == "legacy"
        assert meta["markdown"] is False
        assert meta["mime"] == "text/plain"
        assert meta["size_bytes"] == 5

    async def test_text_markdown_returns_decoded(self) -> None:
        text, meta = await parse_document(b"# t", "text/markdown", "a.md")
        assert text == "# t"
        assert meta["engine"] == "legacy"
        assert meta["markdown"] is False


class TestMarkitdownEngine:
    """markitdown — primary для PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON."""

    async def test_pdf_uses_markitdown_when_enabled(self) -> None:
        with patch(
            "src.backend.services.ai.document_parsers._orchestrator._try_markitdown"
        ) as mock_md:
            mock_md.return_value = ("# Heading\n\nbody", [])
            text, meta = await parse_document(b"%PDF-1.0", "application/pdf", "a.pdf")
            assert text == "# Heading\n\nbody"
            assert meta["engine"] == "markitdown"
            assert meta["markdown"] is True
            mock_md.assert_called_once()

    async def test_pptx_uses_markitdown(self) -> None:
        mime = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        with patch(
            "src.backend.services.ai.document_parsers._orchestrator._try_markitdown"
        ) as mock_md:
            mock_md.return_value = ("## Slide", [])
            text, meta = await parse_document(b"PK\x03\x04", mime, "p.pptx")
            assert text == "## Slide"
            assert meta["engine"] == "markitdown"


class TestMarkitdownFailureFallback:
    """При провале markitdown — legacy fallback для PDF/DOCX/HTML;
    PPTX/XLSX/CSV/JSON → ValueError (нет legacy)."""

    async def test_pdf_falls_back_to_legacy_on_markitdown_failure(self) -> None:
        with patch(
            "src.backend.services.ai.document_parsers._orchestrator._try_markitdown"
        ) as mock_md:
            mock_md.side_effect = RuntimeError("boom")
            with patch(
                "src.backend.services.ai.document_parsers._orchestrator._parse_pdf"
            ) as mock_pdf:
                mock_pdf.return_value = ("plain pdf text", [])
                text, meta = await parse_document(
                    b"%PDF-1.0", "application/pdf", "a.pdf"
                )
        assert text == "plain pdf text"
        assert meta["engine"] == "legacy"
        assert meta["markdown"] is False
        # warning fixed что markitdown упал.
        assert any("markitdown failed" in w for w in meta["warnings"])

    async def test_pptx_raises_when_markitdown_fails_no_fallback(self) -> None:
        mime = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        with patch(
            "src.backend.services.ai.document_parsers._orchestrator._try_markitdown"
        ) as mock_md:
            mock_md.side_effect = RuntimeError("no markitdown")
            with pytest.raises(ValueError, match="markitdown-engine"):
                await parse_document(b"PK\x03\x04", mime, "p.pptx")


class TestMarkitdownDisabled:
    """engine_enabled=False — markitdown пропущен сразу."""

    async def test_engine_disabled_routes_to_legacy(self) -> None:
        from src.backend.core.config.ai import markitdown_settings

        original = markitdown_settings.engine_enabled
        markitdown_settings.engine_enabled = False
        try:
            with patch(
                "src.backend.services.ai.document_parsers._orchestrator._parse_pdf"
            ) as mock_pdf:
                mock_pdf.return_value = ("legacy", [])
                text, meta = await parse_document(
                    b"%PDF-1.0", "application/pdf", "a.pdf"
                )
            assert meta["engine"] == "legacy"
            assert text == "legacy"
        finally:
            markitdown_settings.engine_enabled = original


class TestUnsupportedMime:
    async def test_unknown_mime_raises(self) -> None:
        with pytest.raises(ValueError, match="не поддерживается"):
            await parse_document(b"", "application/x-secret", "a.bin")


def test_supported_mime_types_includes_new_formats() -> None:
    assert (
        "application/vnd.openxmlformats-officedocument."
        "presentationml.presentation" in SUPPORTED_MIME_TYPES
    )
    assert (
        "application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet" in SUPPORTED_MIME_TYPES
    )
    assert "text/html" in SUPPORTED_MIME_TYPES
    assert "text/csv" in SUPPORTED_MIME_TYPES
    assert "application/json" in SUPPORTED_MIME_TYPES
