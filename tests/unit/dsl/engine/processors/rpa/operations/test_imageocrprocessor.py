"""``ImageOcrProcessor.process`` — покрытие (cycle 172, кластер C5).

До cycle 172 процессор не имел тестов на ``process()``: был покрыт
только round-trip (``to_spec()``). Проверяются три ветви:

* успешный OCR (pytesseract замокан — бинарник Tesseract не нужен);
* body не ``bytes`` → ``exchange.fail``;
* ``auth_check`` не прошёл → ранний выход без ``set_out``.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
    ImageOcrProcessor,
)


def _png_bytes() -> bytes:
    """Минимальный валидный PNG (PIL доступна в venv)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _exchange(body: object) -> MagicMock:
    """Заглушка Exchange с нужными атрибутами."""
    exchange = MagicMock()
    exchange.in_message = MagicMock()
    exchange.in_message.body = body
    exchange.in_message.headers = {"content-type": "image/png"}
    exchange.set_out = MagicMock()
    exchange.fail = MagicMock()
    exchange.stop = MagicMock()
    return exchange


class TestImageOcrProcessor:
    """Тесты ``ImageOcrProcessor.process``."""

    @pytest.mark.asyncio
    async def test_process_extracts_text(self) -> None:
        """Успешный OCR → set_out с body {text, lang}."""
        processor = ImageOcrProcessor(lang="eng")
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        exchange = _exchange(_png_bytes())

        with patch("pytesseract.image_to_string", return_value="  hello world  "):
            await processor.process(exchange, MagicMock())

        exchange.set_out.assert_called_once_with(
            body={"text": "hello world", "lang": "eng"},
            headers={"content-type": "image/png"},
        )
        exchange.fail.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_fails_on_non_bytes_body(self) -> None:
        """Body не bytes → exchange.fail, set_out не вызывается."""
        processor = ImageOcrProcessor()
        processor.auth_check = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        exchange = _exchange({"not": "bytes"})

        await processor.process(exchange, MagicMock())

        exchange.fail.assert_called_once_with("ocr expects image bytes")
        exchange.set_out.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_skipped_when_auth_denied(self) -> None:
        """auth_check → False: ранний выход, ничего не меняем."""
        processor = ImageOcrProcessor()
        processor.auth_check = AsyncMock(return_value=False)  # type: ignore[attr-defined]
        exchange = _exchange(_png_bytes())

        await processor.process(exchange, MagicMock())

        exchange.set_out.assert_not_called()
        exchange.fail.assert_not_called()

    def test_to_spec_omits_default_lang(self) -> None:
        """to_spec: дефолтный lang не выгружается, нестандартный — да."""
        assert ImageOcrProcessor().to_spec() == {"ocr": {}}
        assert ImageOcrProcessor(lang="rus").to_spec() == {"ocr": {"lang": "rus"}}
