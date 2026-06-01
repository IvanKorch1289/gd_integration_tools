"""Тесты ImageIngester — извлечение метаданных изображений.

Сценарии:
    * ingest bytes → ChunkDoc(kind="image", content=bytes).
    * Pillow lazy-fallback: при ImportError — metadata содержит warning.
    * caption_provider вызывается, результат записан в metadata.
    * caption_provider падает → warning, но ChunkDoc создан.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.multimodal.image_ingester import ImageIngester
from src.backend.services.ai.rag.multimodal.types import ChunkDoc

# ─── Вспомогательный фикстурный PNG ──────────────────────────────────────────


def _png_bytes() -> bytes:
    """Минимальный валидный PNG (1×1 transparent pixel)."""
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000D49444154789C636400010000000500010D0A2DB40000000049454E44AE426082"
    )


# ─── Тест 1: ingest bytes → ChunkDoc ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_ingester_returns_chunkdoc_for_bytes() -> None:
    """ingest(bytes) возвращает ChunkDoc kind='image' с content=bytes."""
    ingester = ImageIngester(extract_exif=False)
    png = _png_bytes()

    chunk = await ingester.ingest(png)

    assert isinstance(chunk, ChunkDoc)
    assert chunk.kind == "image"
    assert chunk.content == png
    assert chunk.embedding_kind == "clip"
    assert chunk.metadata["size_bytes"] == len(png)
    assert "sha256" in chunk.metadata
    assert chunk.metadata["source_path"] == "<bytes>"


# ─── Тест 2: ingest пути из tmp_path ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_ingester_reads_from_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """ingest(Path) читает файл и заполняет source_path."""
    ingester = ImageIngester(extract_exif=False)
    target = tmp_path / "test.png"
    png = _png_bytes()
    target.write_bytes(png)

    chunk = await ingester.ingest(target)

    assert chunk.kind == "image"
    assert chunk.content == png
    assert chunk.metadata["source_path"] == str(target)


# ─── Тест 3: Pillow недоступен → metadata с warning ──────────────────────────


@pytest.mark.asyncio
async def test_image_ingester_handles_pillow_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ImportError на PIL — metadata содержит warning, ChunkDoc создан."""
    # Удаляем кэшированные модули PIL и подменяем импорт.
    for mod_name in list(sys.modules):
        if mod_name == "PIL" or mod_name.startswith("PIL."):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    real_import = __import__

    def _fake_import(
        name: str, globals=None, locals=None, fromlist=(), level=0
    ):  # type: ignore[no-untyped-def]
        if name == "PIL" or name.startswith("PIL"):
            raise ImportError("PIL отключён для теста")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    ingester = ImageIngester()
    chunk = await ingester.ingest(_png_bytes())

    assert chunk.kind == "image"
    assert chunk.metadata.get("warnings") == ["pillow_not_installed"]


# ─── Тест 4: caption_provider вызывается и результат в metadata ──────────────


@pytest.mark.asyncio
async def test_image_ingester_invokes_caption_provider() -> None:
    """caption_provider(bytes)→str записывается в metadata['caption']."""
    provider = AsyncMock(return_value="cat sitting on a desk")
    ingester = ImageIngester(extract_exif=False, caption_provider=provider)

    chunk = await ingester.ingest(_png_bytes())

    provider.assert_awaited_once()
    assert chunk.metadata["caption"] == "cat sitting on a desk"


# ─── Тест 5: caption_provider падает → warning, ChunkDoc создан ─────────────


@pytest.mark.asyncio
async def test_image_ingester_caption_provider_failure() -> None:
    """Падение caption_provider не ломает ingest; warning в metadata."""
    provider = AsyncMock(side_effect=RuntimeError("VLM out of quota"))
    ingester = ImageIngester(extract_exif=False, caption_provider=provider)

    chunk = await ingester.ingest(_png_bytes())

    assert chunk.kind == "image"
    assert "caption" not in chunk.metadata
    warnings = chunk.metadata.get("warnings", [])
    assert any("caption_failed" in w for w in warnings)
