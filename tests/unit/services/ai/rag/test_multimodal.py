"""Smoke-тесты MultimodalRAGService (K4 W4 scaffold).

Проверяет:
    - feature-flag OFF → ingest не записывает в store, retrieve возвращает [];
    - ingest_text / ingest_image / ingest_audio → MultimodalEntry с embedding;
    - retrieve с modality_filter фильтрует по модальности;
    - retrieve top_k ограничивает количество результатов.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag.multimodal import MultimodalEntry, MultimodalRAGService

# ─── Вспомогательные фикстуры ─────────────────────────────────────────────────


def _make_service(*, enabled: bool) -> MultimodalRAGService:
    """Создаёт MultimodalRAGService с явно заданным значением feature-flag.

    Args:
        enabled: Значение feature_flags.multimodal_rag_enabled.

    Returns:
        Новый экземпляр MultimodalRAGService.
    """
    svc = MultimodalRAGService()
    svc._is_enabled = lambda: enabled  # type: ignore[method-assign]
    return svc


# ─── Тест 1: feature-flag OFF → empty retrieve ────────────────────────────────


@pytest.mark.asyncio
async def test_multimodal_skips_when_flag_off() -> None:
    """При multimodal_rag_enabled=False ingest не пишет в store, retrieve пустой."""
    svc = _make_service(enabled=False)

    entry = await svc.ingest_text("hello world", {"source": "test"})
    # Entry создаётся, но НЕ сохраняется в store
    assert isinstance(entry, MultimodalEntry)
    assert entry.modality == "text"
    assert len(svc._store) == 0

    results = await svc.retrieve("hello world")
    assert results == []


# ─── Тест 2: ingest_text → MultimodalEntry с embedding ───────────────────────


@pytest.mark.asyncio
async def test_ingest_text_returns_entry_with_embedding() -> None:
    """ingest_text создаёт MultimodalEntry с непустым 384-dim embedding."""
    svc = _make_service(enabled=True)

    entry = await svc.ingest_text("банковский кредит", {"namespace": "finance"})

    assert isinstance(entry, MultimodalEntry)
    assert entry.modality == "text"
    assert isinstance(entry.content, str)
    assert entry.content == "банковский кредит"
    assert len(entry.embedding) == 384
    assert all(isinstance(v, float) for v in entry.embedding)
    assert entry.entry_id in svc._store
    assert entry.metadata["namespace"] == "finance"


# ─── Тест 3: ingest_image → MultimodalEntry с bytes content ──────────────────


@pytest.mark.asyncio
async def test_ingest_image_bytes() -> None:
    """ingest_image принимает bytes и создаёт MultimodalEntry modality=image."""
    svc = _make_service(enabled=True)
    fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # заголовок-имитация PNG

    entry = await svc.ingest_image(fake_image, {"filename": "test.png"})

    assert isinstance(entry, MultimodalEntry)
    assert entry.modality == "image"
    assert isinstance(entry.content, bytes)
    assert entry.content == fake_image
    assert len(entry.embedding) == 384
    assert entry.metadata["filename"] == "test.png"
    assert entry.entry_id in svc._store


# ─── Тест 4: ingest_audio → MultimodalEntry с bytes content ──────────────────


@pytest.mark.asyncio
async def test_ingest_audio_bytes() -> None:
    """ingest_audio принимает bytes и создаёт MultimodalEntry modality=audio."""
    svc = _make_service(enabled=True)
    fake_audio = b"RIFF" + b"\x00" * 32 + b"WAVE"  # заголовок-имитация WAV

    entry = await svc.ingest_audio(fake_audio, {"duration_s": 5.0})

    assert isinstance(entry, MultimodalEntry)
    assert entry.modality == "audio"
    assert isinstance(entry.content, bytes)
    assert entry.content == fake_audio
    assert len(entry.embedding) == 384
    assert entry.metadata["duration_s"] == 5.0
    assert entry.entry_id in svc._store


# ─── Тест 5: retrieve с modality_filter ──────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_filters_by_modality() -> None:
    """retrieve с modality_filter=['text'] возвращает только text-записи."""
    svc = _make_service(enabled=True)

    text_entry = await svc.ingest_text("документ о кредитах", {})
    await svc.ingest_image(b"\xff\xd8\xff" + b"\x00" * 16, {})  # jpeg-имитация
    await svc.ingest_audio(b"\x00" * 32, {})

    results = await svc.retrieve("кредиты", modality_filter=["text"])

    assert len(results) == 1
    assert results[0].entry_id == text_entry.entry_id
    assert results[0].modality == "text"


# ─── Тест 6: retrieve top_k ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_top_k() -> None:
    """retrieve(top_k=2) возвращает не более 2 записей из большего store."""
    svc = _make_service(enabled=True)

    for i in range(5):
        await svc.ingest_text(f"документ {i}", {"index": i})

    results = await svc.retrieve("документ", top_k=2)

    assert len(results) == 2
    # Все результаты — MultimodalEntry
    assert all(isinstance(r, MultimodalEntry) for r in results)
