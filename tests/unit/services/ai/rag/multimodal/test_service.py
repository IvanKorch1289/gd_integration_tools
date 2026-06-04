"""Тесты MultimodalRAGService — фасад над PDF/Image + embeddings + search.

Сценарии:
    * ingest_document(image_bytes) → IngestResult с одним image-чанком.
    * ingest_document(pdf_bytes, collection) → chunks в нужной коллекции.
    * search возвращает SearchResult, отсортированный по score.
    * delete_collection удаляет всю коллекцию.
    * feature-flag OFF → ingest/search nooped.
    * неподдерживаемый MIME → ValueError.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.multimodal.service import MultimodalRAGService
from src.backend.services.ai.rag.multimodal.types import IngestResult, SearchResult


def _png_bytes() -> bytes:
    """Минимальный валидный PNG."""
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000D49444154789C636400010000000500010D0A2DB40000000049454E44AE426082"
    )


def _make_service(*, enabled: bool = True) -> MultimodalRAGService:
    """Создаёт MultimodalRAGService с инлайн-override feature-flag."""
    svc = MultimodalRAGService()
    svc._is_enabled = lambda: enabled  # type: ignore[method-assign]
    return svc


# ─── Тест 1: ingest_document(image bytes) ────────────────────────────────────


@pytest.mark.asyncio
async def test_service_ingest_image_bytes() -> None:
    """ingest_document(bytes, mime='image/png') → один image-чанк в коллекции."""
    svc = _make_service()

    result = await svc.ingest_document(
        _png_bytes(), collection="finance", mime="image/png"
    )

    assert isinstance(result, IngestResult)
    assert len(result.chunks) == 1
    assert result.chunks[0].kind == "image"
    assert result.chunks[0].metadata["collection"] == "finance"
    # Эмбеддинг был заполнен (dummy fallback).
    assert result.chunks[0].embedding is not None
    assert len(result.chunks[0].embedding) > 0


# ─── Тест 2: ingest_document(pdf bytes) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_service_ingest_pdf_bytes() -> None:
    """ingest_document с PDF mime → chunks в коллекции."""
    svc = _make_service()
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"  # битый PDF

    result = await svc.ingest_document(
        pdf_bytes, collection="docs", mime="application/pdf"
    )

    # Битый PDF → empty chunks + warning, но без exception.
    assert isinstance(result, IngestResult)
    assert isinstance(result.warnings, list)


# ─── Тест 3: search возвращает SearchResult ──────────────────────────────────


@pytest.mark.asyncio
async def test_service_search_returns_sorted_results() -> None:
    """search возвращает SearchResult, отсортированные по score desc."""
    svc = _make_service()

    # Добавляем 3 image-чанка.
    for _ in range(3):
        await svc.ingest_document(_png_bytes(), collection="default", mime="image/png")

    results = await svc.search("query string", collection="default", top_k=2)

    assert len(results) <= 2
    assert all(isinstance(r, SearchResult) for r in results)
    if len(results) >= 2:
        # Сортировка по убыванию score.
        assert results[0].score >= results[1].score


# ─── Тест 4: delete_collection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_delete_collection() -> None:
    """delete_collection удаляет всю коллекцию, возвращает количество."""
    svc = _make_service()

    for _ in range(2):
        await svc.ingest_document(_png_bytes(), collection="temp", mime="image/png")

    deleted = svc.delete_collection("temp")
    assert deleted == 2

    results = await svc.search("anything", collection="temp")
    assert results == []


# ─── Тест 5: feature-flag OFF → ingest не пишет, search пустой ──────────────


@pytest.mark.asyncio
async def test_service_respects_feature_flag_off() -> None:
    """При флаге OFF: ingest возвращает IngestResult, но в store ничего нет."""
    svc = _make_service(enabled=False)

    result = await svc.ingest_document(
        _png_bytes(), collection="bucket", mime="image/png"
    )
    # Чанки парсятся, но не сохраняются в _collections.
    assert isinstance(result, IngestResult)
    assert "bucket" not in svc._collections

    search = await svc.search("query", collection="bucket")
    assert search == []


# ─── Тест 6: неподдерживаемый MIME → ValueError ──────────────────────────────


@pytest.mark.asyncio
async def test_service_rejects_unsupported_mime() -> None:
    """audio/wav (и любой не PDF/image) → ValueError."""
    svc = _make_service()
    with pytest.raises(ValueError, match="не поддерживается"):
        await svc.ingest_document(b"RIFF....WAVE", collection="x", mime="audio/wav")


# ─── Тест 7: set_embedder подменяет dummy на custom ──────────────────────────


@pytest.mark.asyncio
async def test_service_set_embedder_overrides_dummy() -> None:
    """Кастомный embedder используется вместо sha-dummy."""
    svc = _make_service()
    custom_vec = [9.0, 9.0, 9.0]

    fake_embedder = AsyncMock()
    fake_embedder.embed = AsyncMock(return_value=custom_vec)
    fake_embedder.embedding_kind = "fake-custom"
    svc.set_embedder(fake_embedder)

    result = await svc.ingest_document(_png_bytes(), collection="c", mime="image/png")

    assert result.chunks[0].embedding == custom_vec
    assert result.chunks[0].embedding_kind == "fake-custom"


# ─── Тест 8: bytes без mime → ValueError ─────────────────────────────────────


@pytest.mark.asyncio
async def test_service_bytes_without_mime_rejected() -> None:
    """ingest_document(bytes) без аргумента mime → ValueError."""
    svc = _make_service()
    with pytest.raises(ValueError, match="требуется явный аргумент mime"):
        await svc.ingest_document(_png_bytes(), collection="x")
