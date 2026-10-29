"""S65 W2 — ImageOcrProcessor extracted from rpa/operations.py.

Per-processor file split.

ADR-0393 (волна 18): добавлен предел ожидания OCR. ADR-0368 починил
только ``services/rpa/ocr_processor.py`` — DSL-шаг ``ocr`` остался без
таймаута: ``pytesseract.image_to_string`` hang'ит вызов маршрута навсегда
(и держит worker). Теперь используется тот же двойной предел ожидания
(внутренний timeout pytesseract + внешний ``asyncio.wait_for``).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.utils.image_safety import UnsafeImageError, open_image
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")

#: Предел ожидания OCR в DSL-шаге (секунды) — ADR-0368/ADR-0393.
DEFAULT_OCR_TIMEOUT_SECONDS = 30.0


class ImageOcrProcessor(BaseProcessor):
    """OCR — извлечение текста с изображений через Tesseract.

    Body: bytes (изображение). Результат: ``{"text": "...", "lang": "eng+rus"}``
    (ключи ``text`` и ``lang``).

    Args:
        lang: Код языка Tesseract.
        timeout: Предел ожидания OCR в секундах (default 30.0).
        name: Имя процессора.

    """

    required_capability: ClassVar[str | None] = "rpa.image.ocr"
    audit_event: str | None = "rpa.image.ocr"

    def __init__(
        self,
        *,
        lang: str = "eng+rus",
        timeout: float = DEFAULT_OCR_TIMEOUT_SECONDS,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "ocr")
        self._lang = lang
        self._timeout = timeout

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        if not await self.auth_check(exchange, action="read"):
            return

        body = exchange.in_message.body
        if not isinstance(body, bytes):
            exchange.fail("ocr expects image bytes")
            return
        try:
            import pytesseract
        except ImportError:
            exchange.fail("pytesseract not installed: pip install pytesseract")
            return
        # Единая безопасная точка загрузки изображения (ADR-0388): лимит
        # пикселей, allowlist растровых форматов, понятная доменная ошибка.
        # ``open_image`` гарантирует .close() даже при исключении в
        # pytesseract.image_to_string. PIL держит reference на underlying
        # file пока Image жив; без закрытия это приводит к
        # file-descriptor leak (Sprint 83 W3).
        try:
            with open_image(body) as img:
                # ADR-0368/ADR-0393: двойной предел ожидания — процесс-
                # timeout внутри pytesseract и внешний ``asyncio.wait_for``.
                # Потолок: отмена ``wait_for`` не прерывает поток
                # executor'а, но tesseract-process завершается по
                # собственному timeout.
                text = await asyncio.wait_for(
                    asyncio.to_thread(
                        pytesseract.image_to_string,
                        img,
                        lang=self._lang,
                        timeout=self._timeout,
                    ),
                    timeout=self._timeout,
                )
        except UnsafeImageError as exc:
            # Отклонено политикой безопасной загрузки (ADR-0388):
            # понятная ошибка шага вместо «хиры»-трассировки.
            exchange.fail(str(exc))
            return
        except TimeoutError:
            # ADR-0393: OCR не уложился в лимит — понятная ошибка шага
            # вместо бесконечного ожидания маршрута.
            exchange.fail(
                f"ocr timed out after {self._timeout:.1f}s "
                "(ADR-0368/ADR-0393): увеличьте timeout шага или уменьшите "
                "изображение"
            )
            return
        except pytesseract.TesseractNotFoundError:
            # Бинарник tesseract не установлен → это конфигурация стенда,
            # а не ошибка маршрута: fail-closed через exchange.fail.
            exchange.fail(
                "tesseract executable not found: install tesseract-ocr "
                "and the language packs"
            )
            return
        except ImportError:
            exchange.fail("Pillow not installed: pip install Pillow")
            return
        exchange.set_out(
            body={"text": text.strip(), "lang": self._lang},
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._lang != "eng+rus":
            spec["lang"] = self._lang
        if self._timeout != DEFAULT_OCR_TIMEOUT_SECONDS:
            spec["timeout"] = self._timeout
        return {"ocr": spec}
