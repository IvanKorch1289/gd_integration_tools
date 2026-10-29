"""Тесты ``src.backend.core.utils.image_safety`` (ADR-0388).

Сценарии:
    * валидный PNG открывается, размер/формат читаются;
    * oversize-изображение (decompression bomb) → ``UnsafeImageError``
      с понятным сообщением, а не «хира»-трассировка;
    * SVG / неподдерживаемый формат → ``UnsafeImageError``;
    * мусорные байты → ``UnsafeImageError``;
    * ``PIL.Image.MAX_IMAGE_PIXELS`` синхронизируется с лимитом проекта;
    * ресурсы освобождаются (image.close() вызывается).
"""

from __future__ import annotations

import struct
import sys
import types
import zlib
from typing import Any

import pytest

from src.backend.core.utils.image_safety import (
    ALLOWED_IMAGE_FORMATS,
    MAX_IMAGE_PIXELS,
    UnsafeImageError,
    open_image,
)

# ─── Вспомогательные фикстуры ────────────────────────────────────────────────


def _png_bytes(width: int = 4, height: int = 4) -> bytes:
    """Валидный PNG заданного размера (через Pillow)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _png_header(width: int, height: int) -> bytes:
    """PNG с заявленными размерами (пиксельные данные не декодируются).

    Pillow читает размер из заголовка (IHDR) на этапе ``Image.open`` — этого
    достаточно, чтобы проверить лимит пикселей без генерации гигабайтных
    картинок.
    """

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


def _ppm_bytes() -> bytes:
    """Валидный PPM — Pillow его понимает, но формат вне allowlist'а."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PPM")
    return buffer.getvalue()


class _FakeImage:
    """Минимальный stand-in для ``PIL.Image.Image``."""

    def __init__(self, *, fmt: str = "PNG", width: int = 10, height: int = 10) -> None:
        self.format = fmt
        self.width = width
        self.height = height
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _install_fake_pil(
    monkeypatch: pytest.MonkeyPatch, image: _FakeImage
) -> types.ModuleType:
    """Подменяет ``PIL`` / ``PIL.Image`` на верные mock'и (ADR-0388).

    Мок повторяет контракт реального Pillow: ``MAX_IMAGE_PIXELS``,
    ``DecompressionBombError``, ``DecompressionBombWarning``,
    ``UnidentifiedImageError`` и ``open()``.
    """
    pil_module = types.ModuleType("PIL")
    image_module = types.ModuleType("PIL.Image")
    image_module.MAX_IMAGE_PIXELS = 89_478_485  # type: ignore[attr-defined]
    image_module.DecompressionBombError = type(  # type: ignore[attr-defined]
        "DecompressionBombError", (Exception,), {}
    )
    image_module.DecompressionBombWarning = type(  # type: ignore[attr-defined]
        "DecompressionBombWarning", (Warning,), {}
    )
    image_module.UnidentifiedImageError = type(  # type: ignore[attr-defined]
        "UnidentifiedImageError", (Exception,), {}
    )

    def _open(_fp: Any) -> _FakeImage:
        return image

    image_module.open = _open  # type: ignore[attr-defined]
    pil_module.Image = image_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    return image_module


# ─── Happy path ──────────────────────────────────────────────────────────────


def test_open_image_accepts_valid_png() -> None:
    """Валидный PNG открывается; размер и формат доступны."""
    with open_image(_png_bytes(8, 6)) as image:
        assert image.width == 8
        assert image.height == 6
        assert (image.format or "").upper() == "PNG"


def test_open_image_allows_raster_formats_from_allowlist() -> None:
    """Allowlist форматов непустой и содержит основные растровые."""
    assert {"PNG", "JPEG", "GIF", "BMP", "WEBP"} <= ALLOWED_IMAGE_FORMATS


# ─── Лимит пикселей (decompression bomb) ─────────────────────────────────────


def test_open_image_rejects_oversize_png() -> None:
    """oversize-изображение → UnsafeImageError с понятным сообщением."""
    data = _png_header(10_000, 10_000)  # 100M пикселей > лимита 50M

    with pytest.raises(UnsafeImageError) as exc:
        with open_image(data):
            pass

    message = str(exc.value)
    assert "too large" in message
    assert str(MAX_IMAGE_PIXELS) in message


def test_open_image_rejects_extreme_png() -> None:
    """Экстремальный размер (срабатывает DecompressionBombError) → та же ошибка."""
    data = _png_header(20_000, 20_000)  # 400M пикселей

    with pytest.raises(UnsafeImageError) as exc:
        with open_image(data):
            pass

    assert "too large" in str(exc.value)


def test_open_image_sets_pillow_pixel_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Хелпер синхронизирует ``PIL.Image.MAX_IMAGE_PIXELS`` с лимитом проекта."""
    image_module = _install_fake_pil(monkeypatch, _FakeImage())

    with open_image(b"payload"):
        pass

    assert image_module.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS


# ─── Неподдерживаемые форматы ────────────────────────────────────────────────


def test_open_image_rejects_svg() -> None:
    """SVG (векторный «враппер») отклоняется, а не парсится «как есть»."""
    with pytest.raises(UnsafeImageError) as exc:
        with open_image(_svg_bytes()):
            pass

    assert "unsupported" in str(exc.value)


def test_open_image_rejects_format_outside_allowlist() -> None:
    """Формат, который Pillow понимает, но он вне allowlist'а → отказ."""
    with pytest.raises(UnsafeImageError) as exc:
        with open_image(_ppm_bytes()):
            pass

    message = str(exc.value)
    assert "unsupported image format" in message
    assert "PPM" in message


def test_open_image_rejects_garbage_bytes() -> None:
    """Мусорные байты → понятная доменная ошибка."""
    with pytest.raises(UnsafeImageError) as exc:
        with open_image(b"definitely not an image"):
            pass

    assert "image rejected" in str(exc.value)


# ─── Ресурсы и типы ──────────────────────────────────────────────────────────


def test_open_image_closes_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изображение закрывается при выходе из контекстного менеджера."""
    fake = _FakeImage()
    _install_fake_pil(monkeypatch, fake)

    with open_image(b"payload") as image:
        assert image is fake

    assert fake.close_calls == 1


def test_open_image_closes_image_when_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Исключение в теле ``with`` не оставляет изображение открытым."""
    fake = _FakeImage()
    _install_fake_pil(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="boom"):
        with open_image(b"payload"):
            raise RuntimeError("boom")

    assert fake.close_calls == 1


def test_unsafe_image_error_is_value_error() -> None:
    """``UnsafeImageError`` — наследник ``ValueError`` (совместимость)."""
    assert issubclass(UnsafeImageError, ValueError)
