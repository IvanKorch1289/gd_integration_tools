"""ADR-0368 — OCR-процессор: tesseract без timeout hang'ит RPA-вызов.

До фикса ``pytesseract.image_to_string`` вызывался без ``timeout`` и без
внешнего ``asyncio.wait_for`` → зависший tesseract блокировал вызов
навсегда.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.services.rpa.ocr_processor import PytesseractOCRProcessor


def _fake_pytesseract(func: Any) -> Any:
    module = type("FakePytesseract", (), {})()
    module.image_to_string = func
    return module


@pytest.mark.unit
class TestPytesseractTimeout:
    """PytesseractOCRProcessor.recognize() обязан быть ограничен по времени."""

    async def test_timeout_returns_empty_string(self) -> None:
        def _slow_image_to_string(*args: Any, **kwargs: Any) -> str:
            time.sleep(2.0)
            return "late text"

        with patch.dict(
            "sys.modules", {"pytesseract": _fake_pytesseract(_slow_image_to_string)}
        ):
            processor = PytesseractOCRProcessor()
            started = time.monotonic()
            result = await processor.recognize("/fake.png", lang="eng", timeout=0.2)
            elapsed = time.monotonic() - started

        assert result == ""
        assert elapsed < 1.5, "OCR не ограничен таймаутом"

    async def test_timeout_is_passed_to_pytesseract(self) -> None:
        captured: dict[str, Any] = {}

        def _image_to_string(path: str, lang: str = "eng", **kwargs: Any) -> str:
            captured.update(kwargs)
            return "ok"

        with patch.dict(
            "sys.modules", {"pytesseract": _fake_pytesseract(_image_to_string)}
        ):
            processor = PytesseractOCRProcessor()
            result = await processor.recognize("/fake.png", lang="eng", timeout=7.0)

        assert result == "ok"
        assert captured.get("timeout") == 7.0, "timeout не передан в pytesseract"
