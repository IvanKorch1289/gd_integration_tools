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


# ─── Безопасная загрузка изображения (ADR-0388) ─────────────────────────────


def _oversize_png(width: int = 10_000, height: int = 10_000) -> bytes:
    """PNG с заявленными размерами (пиксели не декодируются)."""
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * (1 + width * 3))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def _svg_bytes() -> bytes:
    """Минимальный SVG-документ (векторный «враппер»)."""
    return (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b"<rect width='10' height='10'/></svg>"
    )


@pytest.mark.asyncio
async def test_process_fails_on_oversize_image() -> None:
    """oversize-изображение → понятная ошибка шага, а не traceback."""
    processor = ImageOcrProcessor()
    processor.auth_check = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    exchange = _exchange(_oversize_png())

    await processor.process(exchange, MagicMock())

    exchange.set_out.assert_not_called()
    exchange.fail.assert_called_once()
    error = exchange.fail.call_args[0][0]
    assert "too large" in error
    assert "50000000" in error


@pytest.mark.asyncio
async def test_process_fails_on_svg() -> None:
    """SVG отклоняется политикой безопасной загрузки."""
    processor = ImageOcrProcessor()
    processor.auth_check = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    exchange = _exchange(_svg_bytes())

    await processor.process(exchange, MagicMock())

    exchange.set_out.assert_not_called()
    exchange.fail.assert_called_once()
    assert "unsupported" in exchange.fail.call_args[0][0]
