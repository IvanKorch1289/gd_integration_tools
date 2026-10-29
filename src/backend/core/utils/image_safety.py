"""Безопасная загрузка пользовательских изображений (ADR-0388).

Pillow 12.x закрывает 59 CVE (5 CRIT), но обновить его до 13.0.0 нельзя:
core-зависимость ``streamlit`` требует ``pillow<13`` (см. ADR-0385, пин
возвращён с обоснованием). Большинство CVE Pillow 12.x — в разборе
изображений (DoS / heap-overflow), поэтому риск снижается **в коде**, а не
только документируется: все места загрузки пользовательских изображений
используют единый хелпер :func:`open_image`, который

* ограничивает размер изображения (число пикселей) — защита от
  decompression-bomb DoS;
* допускает только растровые форматы из allowlist'а (SVG и прочие
  «обёртки» отклоняются);
* переводит ошибки Pillow в понятную доменную ошибку
  :class:`UnsafeImageError` вместо «хиры»-трассировки;
* гарантирует закрытие файлового дескриптора.

Использование::

    from src.backend.core.utils.image_safety import UnsafeImageError, open_image

    try:
        with open_image(payload) as image:
            result = image.resize((100, 100))
    except UnsafeImageError as exc:
        raise MyStepError(str(exc)) from exc

ponytail: ``warnings.catch_warnings`` меняет глобальное состояние Python,
    поэтому warning Pillow превращается в исключение только на время
    ``Image.open``. Потолок: конкурентный поток может сбросить фильтр
    warnings в это окно. Альтернатива (считать пиксели самостоятельно) уже
    реализована как основная проверка — warning-перехват оставлен как
    defense-in-depth.
"""

from __future__ import annotations

import io
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = (
    "ALLOWED_IMAGE_FORMATS",
    "MAX_IMAGE_PIXELS",
    "UnsafeImageError",
    "open_image",
)

#: Максимальное число пикселей одного изображения (50M ≈ 7000×7000).
#:
#: Pillow сам поднимает ``DecompressionBombError`` при ``pixels > 2 *
#: MAX_IMAGE_PIXELS`` и warning — при ``pixels > MAX_IMAGE_PIXELS``. Наш
#: лимит ниже дефолтного Pillow (89 478 485), поэтому «бомба» отсекается
#: ещё до декодирования пикселей.
MAX_IMAGE_PIXELS = 50_000_000

#: Разрешённые растровые форматы.
#:
#: Всё остальное (SVG, PDF, ICO, PPM, XBM, ...) отклоняется: векторные
#: форматы и «обёртки» не нужны для image_resize / OCR / RAG-ингеста и
#: расширяют поверхность атаки разбора изображений.
ALLOWED_IMAGE_FORMATS: frozenset[str] = frozenset(
    {"PNG", "JPEG", "GIF", "BMP", "WEBP", "TIFF"}
)


class UnsafeImageError(ValueError):
    """Изображение отклонено политикой безопасной загрузки.

    Наследует ``ValueError`` — вызывающий код, который уже ловил
    ``ValueError`` при работе с изображениями, продолжит работать без
    изменений.
    """


def _pil_image_module() -> Any:
    """Импортирует модуль ``PIL.Image``.

    Импорт ленивый: Pillow — опциональная зависимость (extras ``rpa`` /
    ``multimodal-rag``), а не base dependency.

    Returns:
        Модуль ``PIL.Image``.

    Raises:
        ImportError: Pillow не установлен.

    """
    from PIL import Image

    return Image


def _enforce_pixel_limit(image_module: Any) -> None:
    """Синхронизирует ``PIL.Image.MAX_IMAGE_PIXELS`` с лимитом проекта.

    Args:
        image_module: Модуль ``PIL.Image``.

    """
    if image_module.MAX_IMAGE_PIXELS != MAX_IMAGE_PIXELS:
        image_module.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _too_large_message(detail: str) -> str:
    """Формирует понятное сообщение об отклонённом по размеру изображении.

    Args:
        detail: Детализация (число пикселей или текст ошибки Pillow).

    Returns:
        Текст ошибки без traceback'а.

    """
    return (
        f"image rejected: image too large ({detail}; limit {MAX_IMAGE_PIXELS} pixels)"
    )


def _rejected(message: str) -> UnsafeImageError:
    """Логирует отклонение изображения и собирает доменную ошибку.

    Args:
        message: Текст ошибки (без traceback'а).

    Returns:
        Исключение ``UnsafeImageError`` с заданным текстом.

    """
    logger.warning("Image rejected: %s", message)
    return UnsafeImageError(message)


def _open_checked(image_module: Any, handle: io.BytesIO) -> Any:
    """Открывает изображение через Pillow и проверяет формат/размер.

    Args:
        image_module: Модуль ``PIL.Image``.
        handle: BytesIO с байтами изображения.

    Returns:
        Открытый объект ``PIL.Image.Image``.

    Raises:
        UnsafeImageError: Изображение слишком большое, формат не поддерживается
            либо файл не является изображением.

    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", image_module.DecompressionBombWarning)
            try:
                image = image_module.open(handle)
            except image_module.DecompressionBombError as exc:
                raise _rejected(_too_large_message(str(exc))) from exc
            except image_module.UnidentifiedImageError as exc:
                raise _rejected(
                    "image rejected: unsupported or corrupted image file"
                ) from exc
    except image_module.DecompressionBombWarning as exc:
        # Pillow отдал warning (пикселей больше лимита) — превращён в ошибку.
        raise _rejected(_too_large_message(str(exc))) from exc

    image_format = (image.format or "").upper()
    if image_format not in ALLOWED_IMAGE_FORMATS:
        image.close()
        raise _rejected(
            "image rejected: unsupported image format "
            f"'{image_format or 'unknown'}' "
            f"(allowed: {', '.join(sorted(ALLOWED_IMAGE_FORMATS))})"
        )

    pixels = image.width * image.height
    if pixels > MAX_IMAGE_PIXELS:
        image.close()
        raise _rejected(_too_large_message(f"{pixels} pixels"))

    return image


@contextmanager
def open_image(data: bytes) -> Iterator[Any]:
    """Открывает пользовательское изображение с проверками безопасности.

    Args:
        data: Байты изображения (пользовательский ввод).

    Yields:
        Открытый объект ``PIL.Image.Image``.

    Raises:
        UnsafeImageError: Изображение слишком большое, формат не поддерживается
            либо файл не является изображением.
        ImportError: Pillow не установлен (опциональная зависимость).

    """
    image_module = _pil_image_module()
    _enforce_pixel_limit(image_module)

    handle = io.BytesIO(data)
    image: Any = None
    try:
        image = _open_checked(image_module, handle)
        yield image
    finally:
        if image is not None:
            image.close()
        handle.close()
