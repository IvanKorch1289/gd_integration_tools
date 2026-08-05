"""Tenant-isolation negative tests для MultimodalRAG (cycle 37, B-11).

Покрывает defense-in-depth post-filter на трёх retrieval-методах:
``MultimodalRAGService.search``, ``MultimodalRAGService.retrieve``
(legacy) и ``MultimodalPipeline.query``.

Сценарии:
    1. Cross-tenant query → пустой результат (ingest под A, query под B).
    2. Mismatched metadata chunks → отфильтрованы на retrieval-фазе.
    3. Ingest без tenant_id → chunks становятся невидимы при scoped query
       (fail-closed через post-filter, без silent passthrough).

Регрессия против cycle 37 P0 (cross-tenant data leak в multimodal).

NB: ``service.ingest_document`` хранит ``ChunkDoc`` (dataclass),
а ``pipeline.ingest`` хранит ``dict`` — это два независимых пути в
``_collections``. Каждый тест ниже использует ОДИН из путей,
чтобы не смешивать storage-форматы.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag.multimodal import MultimodalRAGService
from src.backend.services.ai.rag.multimodal._legacy import _dummy_embedding
from src.backend.services.ai.rag.multimodal.pipeline import MultimodalPipeline
from src.backend.services.ai.rag.multimodal.types import ChunkDoc

# ─── Вспомогательные фикстуры ─────────────────────────────────────────────────


def _make_service(*, enabled: bool = True) -> MultimodalRAGService:
    """Создаёт ``MultimodalRAGService`` с инлайн-override feature-flag."""
    svc = MultimodalRAGService()
    svc._is_enabled = lambda: enabled  # type: ignore[method-assign]
    return svc


def _png_bytes() -> bytes:
    """Минимальный валидный PNG для image-ingest."""
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
        "0000000D49444154789C636400010000000500010D0A2DB40000000049454E44AE426082"
    )


# ─── Тест 1: cross-tenant query → empty (на каждом из 3 retrieval-путей) ──────


@pytest.mark.asyncio
async def test_service_search_cross_tenant_returns_empty() -> None:
    """``service.search`` под tenant_b → [] после ingest под tenant_a."""
    svc = _make_service()
    await svc.ingest_document(
        _png_bytes(), collection="shared", mime="image/png", tenant_id="tenant_a"
    )
    results = await svc.search(
        "tenant_a", collection="shared", top_k=10, tenant_id="tenant_b"
    )
    assert results == [], (
        f"service.search должен вернуть [], got {len(results)} chunk(s) от tenant_a"
    )


@pytest.mark.asyncio
async def test_legacy_retrieve_cross_tenant_returns_empty() -> None:
    """``legacy.retrieve`` под tenant_b → [] после ingest под tenant_a."""
    svc = _make_service()
    await svc.ingest_text("tenant_a document", {}, tenant_id="tenant_a")
    results = await svc.retrieve("tenant_a", top_k=10, tenant_id="tenant_b")
    assert results == [], (
        f"legacy.retrieve должен вернуть [], got {len(results)} entry/entries от tenant_a"
    )


@pytest.mark.asyncio
async def test_pipeline_query_cross_tenant_returns_empty() -> None:
    """``pipeline.query`` под tenant_b → [] после ingest под tenant_a."""
    svc = _make_service()
    pipeline = MultimodalPipeline(svc)
    await pipeline.ingest(
        modal="text",
        payload="секретный тенант-а документ",
        collection="shared",
        tenant_id="tenant_a",
    )
    results = await pipeline.query(
        "tenant_a", collection="shared", top_k=10, tenant_id="tenant_b"
    )
    assert results == [], (
        f"pipeline.query должен вернуть [], got {len(results)} chunk(s) от tenant_a"
    )


# ─── Тест 2: mismatched metadata chunks filtered out ─────────────────────────


@pytest.mark.asyncio
async def test_mismatched_metadata_chunks_filtered_out() -> None:
    """Чанки с чужим ``metadata["tenant_id"]`` отфильтрованы post-filter'ом.

    B-11 fix (cycle 37): даже если кто-то вставил chunk в store напрямую
    (минуя ingest-метод), retrieval отсекает чужие tenant'ы на Python-стороне.
    """
    svc = _make_service()

    # Прямая инъекция в _collections с ЧУЖИМ tenant_id (минуя ingest API).
    bad_chunk = ChunkDoc(
        chunk_id="evil-chunk-1",
        kind="text",
        content="leaked document body",
        embedding=_dummy_embedding("leaked document body"),
        metadata={"tenant_id": "other_tenant", "collection": "shared"},
    )
    svc._collections.setdefault("shared", {})[bad_chunk.chunk_id] = bad_chunk

    # Legitimate tenant_x chunk тоже присутствует.
    good_chunk = ChunkDoc(
        chunk_id="good-chunk-1",
        kind="text",
        content="legitimate document body",
        embedding=_dummy_embedding("legitimate document body"),
        metadata={"tenant_id": "tenant_x", "collection": "shared"},
    )
    svc._collections.setdefault("shared", {})[good_chunk.chunk_id] = good_chunk

    # query под tenant_x — должен видеть ТОЛЬКО good-chunk.
    results = await svc.search(
        "document", collection="shared", top_k=10, tenant_id="tenant_x"
    )

    assert len(results) == 1, f"Должен быть только good-chunk, got {len(results)}"
    assert results[0].chunk.chunk_id == "good-chunk-1"
    assert results[0].chunk.metadata["tenant_id"] == "tenant_x"

    # query под other_tenant — должен видеть ТОЛЬКО bad-chunk.
    results_other = await svc.search(
        "document", collection="shared", top_k=10, tenant_id="other_tenant"
    )
    assert len(results_other) == 1
    assert results_other[0].chunk.chunk_id == "evil-chunk-1"


# ─── Тест 3: ingest без tenant_id → невидим при scoped query ─────────────────


@pytest.mark.asyncio
async def test_ingest_without_tenant_id_filtered_at_service_search() -> None:
    """Ingest БЕЗ tenant_id → ``service.search`` с явным tenant_id → [].

    B-11 fix (cycle 37): post-filter проверяет
    ``chunk.metadata.get("tenant_id") == effective_tenant``. Чанк без
    metadata-тега НЕ ПРОХОДИТ фильтр при scoped query — это fail-closed
    гарантия (вместо silent passthrough).
    """
    svc = _make_service()
    await svc.ingest_document(_png_bytes(), collection="default", mime="image/png")

    hits = await svc.search("any", collection="default", top_k=10, tenant_id="tenant_x")
    assert hits == [], (
        f"Untagged chunks должны быть filtered out, got {len(hits)} hit(s)"
    )


@pytest.mark.asyncio
async def test_ingest_without_tenant_id_filtered_at_legacy_retrieve() -> None:
    """Ingest БЕЗ tenant_id → ``legacy.retrieve`` с явным tenant_id → []."""
    svc = _make_service()
    await svc.ingest_text("untagged legacy text", {})

    legacy_hits = await svc.retrieve("any", top_k=10, tenant_id="tenant_x")
    assert legacy_hits == [], (
        f"legacy.retrieve должен filter untagged, got {len(legacy_hits)} entry/entries"
    )


@pytest.mark.asyncio
async def test_ingest_without_tenant_id_filtered_at_pipeline_query() -> None:
    """Ingest БЕЗ tenant_id → ``pipeline.query`` с явным tenant_id → []."""
    svc = _make_service()
    pipeline = MultimodalPipeline(svc)
    await pipeline.ingest(
        modal="text", payload="untagged pipeline text", collection="default"
    )

    pipeline_hits = await pipeline.query(
        "any", collection="default", top_k=10, tenant_id="tenant_x"
    )
    assert pipeline_hits == [], (
        f"pipeline.query должен filter untagged, got {len(pipeline_hits)} chunk(s)"
    )


# ─── Тест 4: opt-out через ``tenant_id=""`` (explicit passthrough) ───────────


@pytest.mark.asyncio
async def test_explicit_empty_tenant_id_passthrough() -> None:
    """``tenant_id=""`` — явный opt-out, возвращает ВСЕ чанки (legacy).

    B-11 fix (cycle 37): соответствует контракту ``_resolve_effective_tenant_id``
    из ``search_mixin.py`` — empty string → ``None`` → post-filter skip.
    """
    svc = _make_service()
    await svc.ingest_text("tenant_a content", {}, tenant_id="tenant_a")

    results = await svc.retrieve("content", top_k=10, tenant_id="")
    assert len(results) == 1, (
        f"explicit tenant_id='' должен быть opt-out, got {len(results)}"
    )


# ─── Тест 5: same-tenant query видит данные ──────────────────────────────────


@pytest.mark.asyncio
async def test_same_tenant_query_sees_own_data() -> None:
    """Sanity-check: тот же tenant_id на ingest и query → данные видны."""
    svc = _make_service()
    await svc.ingest_text("tenant_a content", {}, tenant_id="tenant_a")

    results = await svc.retrieve("content", top_k=10, tenant_id="tenant_a")
    assert len(results) == 1, (
        f"same-tenant retrieve должен вернуть 1 запись, got {len(results)}"
    )
    assert results[0].metadata["tenant_id"] == "tenant_a"
