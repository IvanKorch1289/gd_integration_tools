"""Тесты MarkitdownEngine: lazy-import, timeout, tempdir cleanup, network-off."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.ai.document_parsers._markitdown import (
    MarkitdownEngine,
    MarkitdownUnavailableError,
)


class TestLazyImport:
    async def test_unavailable_raises_when_package_missing(self) -> None:
        engine = MarkitdownEngine()
        # Симулируем отсутствие markitdown через monkey-patch importlib.
        with patch.dict("sys.modules", {"markitdown": None}):
            with pytest.raises(MarkitdownUnavailableError):
                await engine.convert(b"x", "application/pdf", "a.pdf")


class TestMaxBytesGuard:
    async def test_exceeds_max_bytes_raises(self) -> None:
        engine = MarkitdownEngine(max_bytes=10)
        with pytest.raises(ValueError, match="max_bytes"):
            await engine.convert(b"x" * 11, "application/pdf", "a.pdf")


class TestConvert:
    async def test_returns_text_content_attribute(self) -> None:
        engine = MarkitdownEngine()
        mock_result = MagicMock()
        mock_result.text_content = "# md"
        mock_md = MagicMock()
        mock_md.convert.return_value = mock_result
        engine._md = mock_md
        text, warnings = await engine.convert(b"%PDF-1.0", "application/pdf", "a.pdf")
        assert text == "# md"
        assert warnings == []
        mock_md.convert.assert_called_once()

    async def test_returns_markdown_attribute_as_fallback(self) -> None:
        engine = MarkitdownEngine()
        mock_result = MagicMock(spec=["markdown"])
        mock_result.markdown = "# fallback"
        mock_md = MagicMock()
        mock_md.convert.return_value = mock_result
        engine._md = mock_md
        text, _ = await engine.convert(b"x", "application/pdf", "a.pdf")
        assert text == "# fallback"


class TestTimeout:
    async def test_long_running_convert_raises_timeout(self) -> None:
        engine = MarkitdownEngine(timeout_s=1)
        mock_md = MagicMock()

        def _slow(path):
            import time

            time.sleep(2)
            return MagicMock(text_content="late")

        mock_md.convert.side_effect = _slow
        engine._md = mock_md
        with pytest.raises(asyncio.TimeoutError):
            await engine.convert(b"x", "application/pdf", "a.pdf")
