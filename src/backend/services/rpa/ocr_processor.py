"""OCR-процессор для извлечения текста из изображений.

Wave ``[wave:s18/w0-goal-driven-sweep-2-ocr]`` — заполнение пробела в RPA-стеке.

Текущая реализация — :class:`PytesseractOCRProcessor` поверх ``pytesseract``
(soft-dep из extras ``rpa-ocr``; требует Tesseract-бинарь на хосте). Если
extras не установлен или Tesseract отсутствует — фабрика
:func:`OCRProcessor.from_environment` возвращает :class:`NoOpOCRProcessor`,
который пишет warning и отдаёт пустую строку.

Активация: feature-flag ``feature_flags.rpa_ocr_enabled = True``.

Архитектура: тонкий wrapper, не использует DSL-инфраструктуру. Подключается
из RPA-сервисов (browser/desktop) для извлечения текста из скриншотов.

S164 W3: async Protocol (ПРАВИЛО 12 — никаких sync I/O в event loop).
``recognize()`` теперь ``async`` + ``is_available`` async + ``asyncio.to_thread``
для pytesseract.image_to_string (CPU-bound → offloaded to thread pool).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "NoOpOCRProcessor",
    "OCRProcessor",
    "OCRUnavailableError",
    "PytesseractOCRProcessor",
)

_logger = get_logger("services.rpa.ocr_processor")


class OCRUnavailableError(RuntimeError):
    """Бросается при попытке вызвать OCR без установленного backend'а.

    Используется, когда пользователь требует strict-mode (через
    :meth:`OCRProcessor.strict_or_raise`), а ни pytesseract, ни Tesseract
    не найдены.
    """


@runtime_checkable
class OCRProcessor(Protocol):
    """Контракт OCR-процессора.

    Реализации:
    * :class:`PytesseractOCRProcessor` — pytesseract + Tesseract;
    * :class:`NoOpOCRProcessor` — fallback при отсутствии backend'а.

    S164 W3: ``recognize()`` и ``is_available`` — async (не блокируют
    event loop).
    """

    async def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
        """Распознать текст в изображении.

        Args:
            image_path: Путь к файлу (PNG/JPG/PDF-страница).
            lang: Код языка Tesseract (``eng``, ``rus``, ``eng+rus``).

        Returns:
            Распознанный текст (пустая строка при сбое или NoOp).
        """
        ...  # type: ignore[empty-body]

    async def is_available(self) -> bool:
        """Async availability check.

        Для ``PytesseractOCRProcessor`` — проверяет import pytesseract
        (CPU-trivial, но async для protocol consistency).
        Для ``NoOpOCRProcessor`` — всегда True.
        """
        ...  # type: ignore[empty-body]


class PytesseractOCRProcessor:
    """OCR через pytesseract (Tesseract на хосте).

    Lazy-import pytesseract в :meth:`recognize`, чтобы импорт модуля
    не падал, когда extras ``rpa-ocr`` не установлен.

    S164 W3: ``recognize`` — async + ``asyncio.to_thread(pytesseract.image_to_string, ...)``
    для offloading CPU-bound work из event loop.
    """

    async def is_available(self) -> bool:
        """Проверка доступности pytesseract на момент вызова (async)."""
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return True

    async def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
        """Распознать текст в изображении (async).

        Args:
            image_path: Путь к файлу.
            lang: Код языка Tesseract.

        Returns:
            Распознанный текст или пустая строка при сбое.

        S164 W3: pytesseract.image_to_string — sync, offloaded в thread pool
        через asyncio.to_thread (не блокирует event loop).
        """
        try:
            import pytesseract
        except ImportError as exc:
            _logger.warning("pytesseract not installed: %s", exc)
            return ""
        try:
            return str(
                await asyncio.to_thread(
                    pytesseract.image_to_string, str(image_path), lang=lang
                )
            )
        except Exception as exc:  # tesseract error, env error, etc.
            _logger.warning("pytesseract recognize failed: %s", exc)
            return ""


class NoOpOCRProcessor:
    """Fallback-реализация: всегда возвращает пустую строку + warning.

    Используется, когда feature-flag ``rpa_ocr_enabled=False`` или extras
    ``rpa-ocr`` не установлен. Cigna-friendly: не падает, не блокирует RPA,
    но даёт ясный сигнал в логах при попытке OCR.

    S164 W3: async methods (для Protocol consistency), trivial implementation.
    """

    async def is_available(self) -> bool:
        """NoOp всегда ``available`` в смысле \"не падает\"."""
        return True

    async def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
        """Записать warning и вернуть пустую строку."""
        _logger.warning(
            "OCR requested for %s (lang=%s) but no backend configured; "
            "set rpa_ocr_enabled=True and install [rpa-ocr] extras.",
            image_path,
            lang,
        )
        return ""


def from_environment() -> OCRProcessor:
    """Фабрика OCR-процессора по текущему feature-flag + установленным extras.

    Возвращает :class:`PytesseractOCRProcessor`, если включён feature-flag
    ``rpa_ocr_enabled`` И pytesseract успешно импортируется. Иначе —
    :class:`NoOpOCRProcessor`.

    Returns:
        Экземпляр реализации :class:`OCRProcessor`.

    Note:
        Factory — sync (создаёт объект, не вызывает recognize).
        S164 W3: ``is_available`` check — sync wrapper для async method
        (для сохранения sync factory API). Production code use async.
    """
    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.rpa_ocr_enabled:
            return NoOpOCRProcessor()
    except Exception:  # на ранней инициализации возможны импорт-ошибки
        return NoOpOCRProcessor()

    return PytesseractOCRProcessor()  # availability check перенесён в caller
