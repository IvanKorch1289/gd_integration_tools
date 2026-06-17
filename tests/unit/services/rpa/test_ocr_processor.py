"""Unit tests for src.backend.services.rpa.ocr_processor.

S164 W3: ``recognize()`` и ``is_available`` теперь async (Protocol
consistency, asyncio.to_thread offload).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.rpa.ocr_processor import (
    NoOpOCRProcessor,
    PytesseractOCRProcessor,
    from_environment,
)


class TestNoOpOCRProcessor:
    @pytest.mark.asyncio
    async def test_available(self) -> None:
        proc = NoOpOCRProcessor()
        assert await proc.is_available() is True

    @pytest.mark.asyncio
    async def test_recognize(self, caplog: pytest.LogCaptureFixture) -> None:
        proc = NoOpOCRProcessor()
        with caplog.at_level("WARNING"):
            result = await proc.recognize("/img.png", lang="eng")
        assert result == ""
        assert "no backend configured" in caplog.text


class TestPytesseractOCRProcessor:
    @pytest.mark.asyncio
    async def test_available_when_installed(self) -> None:
        with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
            proc = PytesseractOCRProcessor()
            assert await proc.is_available() is True

    @pytest.mark.asyncio
    async def test_not_installed(self) -> None:
        with patch.dict("sys.modules", {"pytesseract": None}):
            proc = PytesseractOCRProcessor()
            assert await proc.is_available() is False

    @pytest.mark.asyncio
    async def test_recognize_success(self) -> None:
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "hello"
        with patch.dict("sys.modules", {"pytesseract": fake_pt}):
            proc = PytesseractOCRProcessor()
            result = await proc.recognize("/img.png")
            assert result == "hello"
            fake_pt.image_to_string.assert_called_once_with("/img.png", lang="eng")

    @pytest.mark.asyncio
    async def test_recognize_import_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch.dict("sys.modules", {"pytesseract": None}):
            proc = PytesseractOCRProcessor()
            with caplog.at_level("WARNING"):
                result = await proc.recognize("/img.png")
            assert result == ""
        assert "pytesseract not installed" in caplog.text

    @pytest.mark.asyncio
    async def test_recognize_runtime_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_pt = MagicMock()
        fake_pt.image_to_string.side_effect = RuntimeError("tess fail")
        with patch.dict("sys.modules", {"pytesseract": fake_pt}):
            proc = PytesseractOCRProcessor()
            with caplog.at_level("WARNING"):
                result = await proc.recognize("/img.png")
            assert result == ""
        assert "recognize failed" in caplog.text


class TestFromEnvironment:
    def test_feature_flag_off(self) -> None:
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = False
            proc = from_environment()
        assert isinstance(proc, NoOpOCRProcessor)

    def test_feature_flag_on_no_pytesseract(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # S164 W3: from_environment now returns PytesseractOCRProcessor
        # without async availability check (sync factory API).
        # Caller должен проверять is_available() async после factory.
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = True
            with patch.dict("sys.modules", {"pytesseract": None}):
                proc = from_environment()
        # Factory returns PytesseractOCRProcessor (sync, no async check).
        # Caller is expected to verify via await proc.is_available().
        assert isinstance(proc, PytesseractOCRProcessor)

    def test_feature_flag_on_ok(self) -> None:
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = True
            with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
                proc = from_environment()
        assert isinstance(proc, PytesseractOCRProcessor)

    def test_import_error_early(self) -> None:
        # S164 W3: patch the MODULE (not feature_flags attribute), so
        # ``from src.backend.core.config.features import feature_flags``
        # raises ImportError. MagicMock attribute side_effect doesn't
        # propagate through ``from X import Y`` syntax.
        with patch(
            "src.backend.core.config.features", side_effect=ImportError
        ):
            proc = from_environment()
        assert isinstance(proc, NoOpOCRProcessor)