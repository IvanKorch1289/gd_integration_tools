"""Тесты ImageResizeProcessor (S83 W3 PIL leak fix).

Сценарии:
    * Happy path: bytes → resized bytes валидного PNG.
    * ``to_spec()`` сериализует width/height/format.
    * Body не bytes → exchange.fail.
    * **PIL resource cleanup**: Image.open вызывается через context manager;
      ``img.close()`` вызывается автоматически даже если resize/save падает.
    * ``resize`` падает с исключением → ресурс всё равно освобождён.
    * Размеры не заданы → bytes копируются без resize.
"""

# ruff: noqa: S101

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa.operations.imageresizeprocessor import (
    ImageResizeProcessor,
)


def _exchange_with(body: Any) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _make_png(width: int = 10, height: int = 10, color: str = "red") -> bytes:
    """Генерирует валидный PNG bytes для тестов."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_resize_resizes_to_target_dimensions() -> None:
    """bytes 10×10 → resize 50×50 → валидный PNG."""
    proc = ImageResizeProcessor(width=50, height=50, output_format="PNG")
    ex = _exchange_with(_make_png(10, 10))

    await proc.process(ex, context=MagicMock())

    assert ex.status != ExchangeStatus.failed
    out = ex.out_message.body
    assert isinstance(out, bytes)
    from PIL import Image

    with Image.open(io.BytesIO(out)) as result:
        assert result.size == (50, 50)
        assert result.format == "PNG"


@pytest.mark.asyncio
async def test_image_resize_keeps_aspect_by_width() -> None:
    """Только width задан — высота пропорциональна."""
    proc = ImageResizeProcessor(width=20, output_format="PNG")
    ex = _exchange_with(_make_png(40, 10))

    await proc.process(ex, context=MagicMock())

    from PIL import Image

    with Image.open(io.BytesIO(ex.out_message.body)) as result:
        assert result.size == (20, 5)


@pytest.mark.asyncio
async def test_image_resize_keeps_aspect_by_height() -> None:
    """Только height задан — ширина пропорциональна."""
    proc = ImageResizeProcessor(height=30, output_format="PNG")
    ex = _exchange_with(_make_png(20, 60))

    await proc.process(ex, context=MagicMock())

    from PIL import Image

    with Image.open(io.BytesIO(ex.out_message.body)) as result:
        assert result.size == (10, 30)


# ─── Validation ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_resize_rejects_non_bytes_body() -> None:
    """Body не bytes → exchange.fail без побочных эффектов."""
    proc = ImageResizeProcessor(width=10, height=10)
    ex = _exchange_with("not bytes")  # type: ignore[arg-type]

    await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed
    assert "bytes" in (ex.error or "")


# ─── to_spec сериализация ───────────────────────────────────────────────────


def test_image_resize_to_spec_full() -> None:
    """to_spec содержит width/height/output_format."""
    proc = ImageResizeProcessor(width=100, height=200, output_format="JPEG")
    spec = proc.to_spec()
    assert spec == {
        "image_resize": {"width": 100, "height": 200, "output_format": "JPEG"}
    }


def test_image_resize_to_spec_no_dimensions() -> None:
    """Без width/height в spec не попадает None-ключей."""
    proc = ImageResizeProcessor()
    spec = proc.to_spec()
    assert spec == {"image_resize": {}}


def test_image_resize_to_spec_omits_default_png() -> None:
    """``output_format="PNG"`` опускается (default)."""
    proc = ImageResizeProcessor(width=10)
    spec = proc.to_spec()
    assert spec == {"image_resize": {"width": 10}}
    assert "output_format" not in spec["image_resize"]


# ─── PIL resource cleanup (S83 W3 leak fix) ────────────────────────────────


class _TrackedImage:
    """Context-manager-aware замена PIL.Image для проверки .close().

    PIL.Image.open возвращает Image, который поддерживает
    ``__enter__``/``__exit__`` (context manager). ``__exit__`` вызывает
    ``self.close()``. Этот класс отслеживает вызовы, чтобы тесты могли
    проверить, что .close() сработал.
    """

    def __init__(self) -> None:
        self.close_calls = 0
        self.closed = False
        self.resize_calls = 0
        self.save_calls = 0
        self.copy_calls = 0
        # Реальное PIL.Image для size/width/height и save (тесту нужны
        # корректные bytes, чтобы пройти resize-логику в процессоре).
        from PIL import Image as _PIL

        self._real = _PIL.new("RGB", (32, 24), "blue")
        self.width = self._real.width
        self.height = self._real.height
        self.format = "PNG"

    def resize(self, size: tuple[int, int]) -> _TrackedImage:
        self.resize_calls += 1
        self._real = self._real.resize(size)
        self.width = size[0]
        self.height = size[1]
        return self

    def copy(self) -> _TrackedImage:
        self.copy_calls += 1
        new = _TrackedImage()
        new._real = self._real.copy()
        return new

    def save(self, buf: Any, format: str) -> None:
        self.save_calls += 1
        self._real.save(buf, format=format)

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def __enter__(self) -> _TrackedImage:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def _install_tracked_pil_open(
    monkeypatch: pytest.MonkeyPatch, tracker: list[_TrackedImage]
) -> None:
    """Подменяет ``PIL.Image.open`` на factory, возвращающую _TrackedImage.

    Использует ``setattr`` на ``PIL.Image.open`` напрямую, поэтому
    import-кеш не мешает: ленивый ``from PIL import Image`` в процессоре
    получает реальный модуль, но ``Image.open`` уже подменён.
    """
    from PIL import Image as _real_pil_image

    def _factory(_fp: Any) -> _TrackedImage:
        tracker.append(_TrackedImage())
        return tracker[-1]

    monkeypatch.setattr(_real_pil_image, "open", _factory)


def _install_raising_pil_open(
    monkeypatch: pytest.MonkeyPatch, tracker: list[_TrackedImage]
) -> None:
    """Версия с Image, который бросает RuntimeError на resize()."""
    from PIL import Image as _real_pil_image

    class _RaisingImage(_TrackedImage):
        def resize(self, size: tuple[int, int]) -> _TrackedImage:
            raise RuntimeError("simulated resize failure")

    def _factory(_fp: Any) -> _TrackedImage:
        tracker.append(_RaisingImage())
        return tracker[-1]

    monkeypatch.setattr(_real_pil_image, "open", _factory)


async def _passthrough_to_thread(
    func: Any, *args: Any, **kwargs: Any
) -> Any:
    """Подмена ``asyncio.to_thread`` — выполняет func синхронно.

    Нужна для теста, который провоцирует синхронное исключение в resize.
    """

    def _runner() -> Any:
        return func(*args, **kwargs)

    try:
        return _runner()
    except Exception:
        raise


@pytest.mark.asyncio
async def test_image_resize_uses_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Image.open`` обёрнут в ``with`` — .close() вызывается."""
    tracker: list[_TrackedImage] = []
    _install_tracked_pil_open(monkeypatch, tracker)

    proc = ImageResizeProcessor(width=16, height=16, output_format="PNG")
    ex = _exchange_with(_make_png(20, 20))

    await proc.process(ex, context=MagicMock())

    assert ex.status != ExchangeStatus.failed
    assert len(tracker) == 1
    # Context manager __exit__ вызвал .close() минимум один раз.
    assert tracker[0].close_calls >= 1
    assert tracker[0].closed is True
    assert tracker[0].resize_calls == 1


@pytest.mark.asyncio
async def test_image_resize_releases_on_resize_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resize() бросает исключение → Image.close() всё равно вызван.

    Без ``with`` блока PIL.Image.open() удерживает reference на
    underlying file → file-descriptor leak. Тест подтверждает, что
    context manager гарантирует cleanup даже при исключении.
    Исключение из ``_resize`` пробрасывается наружу (unexpected error),
    но ``Image.close()`` вызывается через ``__exit__`` ДО этого.
    """
    tracker: list[_TrackedImage] = []
    _install_raising_pil_open(monkeypatch, tracker)

    proc = ImageResizeProcessor(width=16, height=16, output_format="PNG")
    ex = _exchange_with(_make_png(20, 20))

    with patch(
        "src.backend.dsl.engine.processors.rpa.operations.imageresizeprocessor.asyncio.to_thread",
        new=_passthrough_to_thread,
    ):
        with pytest.raises(RuntimeError, match="simulated resize failure"):
            await proc.process(ex, context=MagicMock())

    # Image был открыт и закрыт ДО пробрасывания RuntimeError.
    assert len(tracker) == 1
    assert tracker[0].closed is True
    assert tracker[0].close_calls >= 1


@pytest.mark.asyncio
async def test_image_resize_no_dimensions_copies_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без width/height выполняется src.copy() + save — Image закрывается."""
    tracker: list[_TrackedImage] = []
    _install_tracked_pil_open(monkeypatch, tracker)

    proc = ImageResizeProcessor()  # без width/height
    ex = _exchange_with(_make_png(8, 8))

    await proc.process(ex, context=MagicMock())

    assert ex.status != ExchangeStatus.failed
    assert len(tracker) == 1
    assert tracker[0].close_calls >= 1
    assert tracker[0].save_calls == 1
