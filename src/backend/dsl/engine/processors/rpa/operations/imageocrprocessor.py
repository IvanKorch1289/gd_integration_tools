"""S65 W2 — ImageOcrProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class ImageOcrProcessor(BaseProcessor):
    """OCR — извлечение текста с изображений через Tesseract.

    Body: bytes (изображение). Результат: {"text": "...", "confidence": float}
    """

    required_capability: ClassVar[str | None] = "rpa.image.ocr"
    audit_event: str | None = "rpa.image.ocr"

    def __init__(self, *, lang: str = "eng+rus", name: str | None = None) -> None:
        super().__init__(name=name or "ocr")
        self._lang = lang

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        if not await self.auth_check(exchange, action="read"):
            return
        import io

        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            exchange.fail(
                "pytesseract/Pillow not installed: pip install pytesseract Pillow",
            )
            return
        body = exchange.in_message.body
        if not isinstance(body, bytes):
            exchange.fail("ocr expects image bytes")
            return
        # ``with Image.open(...)`` гарантирует .close() даже при
        # исключении в pytesseract.image_to_string. PIL держит
        # reference на underlying file пока Image жив; без ``with``
        # это приводит к file-descriptor leak (Sprint 83 W3).
        with Image.open(io.BytesIO(body)) as img:
            text = await asyncio.to_thread(
                pytesseract.image_to_string, img, lang=self._lang,
            )
        exchange.set_out(
            body={"text": text.strip(), "lang": self._lang},
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._lang != "eng+rus":
            spec["lang"] = self._lang
        return {"ocr": spec}
