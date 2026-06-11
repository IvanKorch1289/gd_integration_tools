from __future__ import annotations

"""S65 W2 — ImageResizeProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class ImageResizeProcessor(BaseProcessor):
    """Ресайз и конвертация изображений через Pillow.

    Body: bytes. Результат: bytes (resized image).
    """

    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        output_format: str = "PNG",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"image_resize({width}x{height})")
        self._width = width
        self._height = height
        self._format = output_format.upper()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import io

        try:
            from PIL import Image
        except ImportError:
            exchange.fail("Pillow not installed: pip install Pillow")
            return
        body = exchange.in_message.body
        if not isinstance(body, bytes):
            exchange.fail("image_resize expects bytes")
            return

        def _resize() -> bytes:
            with Image.open(io.BytesIO(body)) as img:
                if self._width and self._height:
                    img = img.resize((self._width, self._height))
                elif self._width:
                    ratio = self._width / img.width
                    img = img.resize((self._width, int(img.height * ratio)))
                elif self._height:
                    ratio = self._height / img.height
                    img = img.resize((int(img.width * ratio), self._height))
                buf = io.BytesIO()
                img.save(buf, format=self._format)
                return buf.getvalue()

        result = await asyncio.to_thread(_resize)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._width is not None:
            spec["width"] = self._width
        if self._height is not None:
            spec["height"] = self._height
        if self._format != "PNG":
            spec["output_format"] = self._format
        return {"image_resize": spec}
