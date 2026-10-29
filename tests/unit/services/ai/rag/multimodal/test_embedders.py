"""Тесты CLIPEmbedder / ColpaliEmbedder.

Сценарии:
    * CLIPEmbedder.embed(text) с mocked SentenceTransformer → list[float].
    * CLIPEmbedder.embed(image bytes) с mocked PIL+ST → list[float].
    * CLIPEmbedder.embed без sentence-transformers → LazyImportError.
    * ColpaliEmbedder.embed без colpali_engine → LazyImportError.
    * EmbedderProtocol — CLIPEmbedder соответствует runtime_checkable.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.rag.multimodal.embedders import (
    CLIPEmbedder,
    ColpaliEmbedder,
    LazyImportError,
)
from src.backend.services.ai.rag.multimodal.protocols import EmbedderProtocol

# ─── Helper: подменяет sys.modules для lazy-import ───────────────────────────


def _install_fake_pil(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Подменяет PIL/PIL.Image на mock с верным контрактом (ADR-0388).

    ``open_image`` проверяет формат и число пикселей, поэтому mock
    повторяет реальный контракт Pillow: ``format``/``width``/``height`` и
    классы ``DecompressionBomb*`` / ``UnidentifiedImageError``.

    Args:
        monkeypatch: pytest fixture.

    Returns:
        Mock-инстанс изображения.

    """
    fake_image = MagicMock()
    fake_image.format = "PNG"
    fake_image.width = 4
    fake_image.height = 4

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
    image_module.open = MagicMock(return_value=fake_image)  # type: ignore[attr-defined]
    pil_module.Image = image_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    return fake_image


def _install_fake_sentence_transformers(
    monkeypatch: pytest.MonkeyPatch, encode_return: list[float]
) -> MagicMock:
    """Подменяет sentence_transformers.SentenceTransformer на mock.

    Args:
        monkeypatch: pytest fixture.
        encode_return: Возвращаемое значение из encode (numpy-like).

    Returns:
        Mock-инстанс модели для assert'ов.

    """
    model_instance = MagicMock()
    fake_array = SimpleNamespace(
        flatten=lambda: SimpleNamespace(tolist=lambda: encode_return)
    )
    model_instance.encode.return_value = fake_array

    fake_module = MagicMock()
    fake_module.SentenceTransformer = MagicMock(return_value=model_instance)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    return model_instance


# ─── Тест 1: CLIPEmbedder.embed(text) с mocked ST ────────────────────────────


@pytest.mark.asyncio
async def test_clip_embedder_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLIPEmbedder.embed(str) возвращает list[float] через ST.encode."""
    model = _install_fake_sentence_transformers(monkeypatch, [0.1, 0.2, 0.3])
    embedder = CLIPEmbedder()

    vec = await embedder.embed("банковский кредит")

    assert vec == [0.1, 0.2, 0.3]
    model.encode.assert_called_once()
    assert embedder.embedding_kind == "clip"


# ─── Тест 2: CLIPEmbedder.embed(bytes) с mocked PIL ──────────────────────────


@pytest.mark.asyncio
async def test_clip_embedder_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLIPEmbedder.embed(bytes) использует безопасную загрузку + ST.encode."""
    _install_fake_sentence_transformers(monkeypatch, [0.5, 0.6])
    _install_fake_pil(monkeypatch)

    embedder = CLIPEmbedder()
    vec = await embedder.embed(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    assert vec == [0.5, 0.6]


@pytest.mark.asyncio
async def test_clip_embedder_rejects_oversize_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """oversize-изображение → доменная ошибка, а не traceback Pillow."""
    import struct
    import zlib

    from src.backend.core.utils.image_safety import UnsafeImageError

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    width = height = 10_000
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * (1 + width * 3))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )

    _install_fake_sentence_transformers(monkeypatch, [0.1])
    embedder = CLIPEmbedder()

    with pytest.raises(UnsafeImageError, match="too large"):
        await embedder.embed(png)


# ─── Тест 3: CLIPEmbedder.embed без ST → LazyImportError ─────────────────────


@pytest.mark.asyncio
async def test_clip_embedder_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без sentence-transformers .embed поднимает LazyImportError."""
    # Стираем кеш и блокируем импорт.
    for name in list(sys.modules):
        if name.startswith("sentence_transformers"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = __import__

    def _blocker(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name.startswith("sentence_transformers"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocker)

    embedder = CLIPEmbedder()
    with pytest.raises(LazyImportError, match="sentence-transformers"):
        await embedder.embed("текст")


# ─── Тест 4: ColpaliEmbedder.embed без colpali → LazyImportError ─────────────


@pytest.mark.asyncio
async def test_colpali_embedder_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без colpali_engine .embed поднимает LazyImportError."""
    for name in list(sys.modules):
        if name.startswith("colpali_engine"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = __import__

    def _blocker(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name.startswith("colpali_engine"):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocker)

    embedder = ColpaliEmbedder()
    with pytest.raises(LazyImportError, match="colpali_engine"):
        await embedder.embed("текст")


# ─── Тест 5: EmbedderProtocol runtime-isinstance ─────────────────────────────


def test_clip_embedder_implements_protocol() -> None:
    """CLIPEmbedder и ColpaliEmbedder совместимы с EmbedderProtocol."""
    assert isinstance(CLIPEmbedder(), EmbedderProtocol)
    assert isinstance(ColpaliEmbedder(), EmbedderProtocol)


# ─── Тест 6: CLIPEmbedder отказывает на неподдерживаемом типе ───────────────


@pytest.mark.asyncio
async def test_clip_embedder_rejects_invalid_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``embed(int)`` → ValueError; ML-deps не требуется."""
    _install_fake_sentence_transformers(monkeypatch, [0.0])
    embedder = CLIPEmbedder()
    with pytest.raises(ValueError, match="неподдерживаемый тип"):
        await embedder.embed(12345)  # type: ignore[arg-type]


# ─── Тест 7: CLIPEmbedder кеширует модель между вызовами ────────────────────


@pytest.mark.asyncio
async def test_clip_embedder_caches_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """SentenceTransformer вызывается только один раз для серии embed."""
    _install_fake_sentence_transformers(monkeypatch, [1.0])

    fake_module = sys.modules["sentence_transformers"]
    embedder = CLIPEmbedder()

    await embedder.embed("text-1")
    await embedder.embed("text-2")
    await embedder.embed("text-3")

    # SentenceTransformer был вызван один раз; encode — три раза.
    assert fake_module.SentenceTransformer.call_count == 1  # type: ignore[attr-defined]
