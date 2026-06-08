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
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from src.backend.infrastructure.logging.factory import get_logger

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
    """

    def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
        """Распознать текст в изображении.

        Args:
            image_path: Путь к файлу (PNG/JPG/PDF-страница).
            lang: Код языка Tesseract (``eng``, ``rus``, ``eng+rus``).

        Returns:
            Распознанный текст (пустая строка при сбое или NoOp).
        """

    @property
    def is_available(self) -> bool:
        """True если backend доступен и готов к работе."""


class PytesseractOCRProcessor:
    """OCR через pytesseract (Tesseract на хосте).

    Lazy-import pytesseract в :meth:`recognize`, чтобы импорт модуля
    не падал, когда extras ``rpa-ocr`` не установлен.
    """

    @property
    def is_available(self) -> bool:
        """Проверка доступности pytesseract на момент вызова."""
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return True

    def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
        """Распознать текст в изображении.

        Args:
            image_path: Путь к файлу.
            lang: Код языка Tesseract.

        Returns:
            Распознанный текст или пустая строка при сбое.
        """
        try:
            import pytesseract
        except ImportError as exc:
            _logger.warning("pytesseract not installed: %s", exc)
            return ""
        try:
            return str(pytesseract.image_to_string(str(image_path), lang=lang))
        except Exception as exc:  # tesseract error, env error, etc.
            _logger.warning("pytesseract recognize failed: %s", exc)
            return ""


class NoOpOCRProcessor:
    """Fallback-реализация: всегда возвращает пустую строку + warning.

    Используется, когда feature-flag ``rpa_ocr_enabled=False`` или extras
    ``rpa-ocr`` не установлен. Cigna-friendly: не падает, не блокирует RPA,
    но даёт ясный сигнал в логах при попытке OCR.
    """

    @property
    def is_available(self) -> bool:
        """NoOp всегда `available` в смысле "не падает"."""
        return True

    def recognize(self, image_path: str | Path, *, lang: str = "eng") -> str:
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
    """
    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.rpa_ocr_enabled:
            return NoOpOCRProcessor()
    except Exception:  # на ранней инициализации возможны импорт-ошибки
        return NoOpOCRProcessor()

    candidate = PytesseractOCRProcessor()
    if not candidate.is_available:
        _logger.warning(
            "rpa_ocr_enabled=True, но pytesseract не установлен; "
            "fallback на NoOpOCRProcessor."
        )
        return NoOpOCRProcessor()
    return candidate
