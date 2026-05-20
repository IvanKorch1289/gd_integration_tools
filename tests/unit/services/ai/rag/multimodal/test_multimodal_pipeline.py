"""Тесты Sprint 11 K4 W2 — MultimodalPipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.multimodal.pipeline import (
    CrossModalQueryResult,
    MultimodalPipeline,
)
from src.backend.services.ai.rag.multimodal.service import MultimodalRAGService


@pytest.mark.asyncio
async def test_pipeline_ingest_text_appends_chunk() -> None:
    """Text payload → chunk попадает в коллекцию service."""
    service = MultimodalRAGService()
    pipeline = MultimodalPipeline(service)

    chunk_id = await pipeline.ingest(
        modal="text",
        payload="hello multimodal world",
        collection="kb",
    )

    assert chunk_id
    assert "kb" in service._collections
    assert chunk_id in service._collections["kb"]


@pytest.mark.asyncio
async def test_pipeline_ingest_image_calls_captioner() -> None:
    """Image payload → caption_image() вызывается, caption становится chunk content."""
    service = MultimodalRAGService()
    service.caption_image = AsyncMock(return_value="cat on a couch")
    pipeline = MultimodalPipeline(service)

    chunk_id = await pipeline.ingest(
        modal="image",
        payload=b"FAKE_IMAGE_BYTES",
        collection="kb",
    )

    service.caption_image.assert_awaited_once()
    stored = service._collections["kb"][chunk_id]
    assert stored["content"] == "cat on a couch"
    assert stored["metadata"]["modal"] == "image"


@pytest.mark.asyncio
async def test_pipeline_ingest_audio_calls_whisper() -> None:
    """Audio payload → transcribe_audio() вызывается."""
    service = MultimodalRAGService()
    service.transcribe_audio = AsyncMock(return_value="привет как дела")
    pipeline = MultimodalPipeline(service)

    chunk_id = await pipeline.ingest(
        modal="audio",
        payload=b"FAKE_WAV",
        collection="kb",
    )
    service.transcribe_audio.assert_awaited_once()
    assert service._collections["kb"][chunk_id]["content"] == "привет как дела"
    assert service._collections["kb"][chunk_id]["metadata"]["modal"] == "audio"


@pytest.mark.asyncio
async def test_cross_modal_retrieval_returns_all_modalities() -> None:
    """Query без filter возвращает результаты разных модальностей."""
    service = MultimodalRAGService()
    pipeline = MultimodalPipeline(service)
    await pipeline.ingest(modal="text", payload="cat dog", collection="kb")
    service.caption_image = AsyncMock(return_value="cat playing")
    await pipeline.ingest(modal="image", payload=b"img", collection="kb")
    service.transcribe_audio = AsyncMock(return_value="dog barking loud")
    await pipeline.ingest(modal="audio", payload=b"wav", collection="kb")

    results = await pipeline.query("cat dog", collection="kb", top_k=10)
    modalities = {r.modal for r in results}
    assert {"text", "image", "audio"}.issubset(modalities)
    assert all(isinstance(r, CrossModalQueryResult) for r in results)


@pytest.mark.asyncio
async def test_modal_filter_restricts_results() -> None:
    """``modal_filter="image"`` возвращает только image-чанки."""
    service = MultimodalRAGService()
    pipeline = MultimodalPipeline(service)
    await pipeline.ingest(modal="text", payload="some text", collection="kb")
    service.caption_image = AsyncMock(return_value="image caption")
    await pipeline.ingest(modal="image", payload=b"img", collection="kb")

    only_images = await pipeline.query("text", collection="kb", modal_filter="image")
    assert all(r.modal == "image" for r in only_images)
