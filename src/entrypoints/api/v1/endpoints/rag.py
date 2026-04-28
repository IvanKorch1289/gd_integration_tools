"""RAG API — публичный CRUD к ``RAGService``.

* ``POST /ingest``  — загрузить документ (chunking + embedding + upsert).
* ``POST /search``  — семантический поиск top-k.
* ``POST /augment`` — подтянуть контекст и вернуть готовый prompt.
* ``DELETE /{doc_id}`` — удалить chunks по id.
* ``GET /stats``    — количество документов в store.

Все ответы — JSON. Если ``rag_settings.enabled = False`` — каждый
endpoint возвращает 503, чтобы не дёргать неподнятый Qdrant.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.core.config.rag import rag_settings
from src.services.ai.rag_service import get_rag_service

__all__ = ("router",)

router = APIRouter()


class IngestRequest(BaseModel):
    """Документ на загрузку в RAG."""

    content: str = Field(..., min_length=1, description="Текст документа.")
    namespace: str = Field(
        default="default", description="Логическая партиция в коллекции."
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Произвольные мета-поля для фильтрации."
    )


class IngestResponse(BaseModel):
    doc_id: str = Field(..., description="Идентификатор документа (sha256 prefix).")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Поисковый запрос.")
    top_k: int = Field(default=5, ge=1, le=100)
    namespace: str | None = Field(default=None)


class SearchHit(BaseModel):
    id: str
    document: str
    metadata: dict[str, Any]
    distance: float


class SearchResponse(BaseModel):
    items: list[SearchHit]


class AugmentRequest(BaseModel):
    query: str = Field(..., min_length=1)
    system_prompt: str = Field(default="", description="Системная инструкция.")
    top_k: int = Field(default=5, ge=1, le=100)
    namespace: str | None = Field(default=None)


class AugmentResponse(BaseModel):
    prompt: str = Field(..., description="Готовый prompt с RAG-контекстом.")


class StatsResponse(BaseModel):
    enabled: bool
    backend: str
    embedding_provider: str
    count: int


def _check_enabled() -> None:
    if not rag_settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG отключён (rag_settings.enabled=False).",
        )


@router.post("/ingest", response_model=IngestResponse, summary="Загрузить документ")
async def ingest(payload: IngestRequest) -> IngestResponse:
    _check_enabled()
    service = get_rag_service()
    doc_id = await service.ingest(
        content=payload.content, metadata=payload.metadata, namespace=payload.namespace
    )
    return IngestResponse(doc_id=doc_id)


@router.post("/search", response_model=SearchResponse, summary="Семантический поиск")
async def search(payload: SearchRequest) -> SearchResponse:
    _check_enabled()
    service = get_rag_service()
    hits = await service.search(
        query=payload.query, top_k=payload.top_k, namespace=payload.namespace
    )
    return SearchResponse(items=[SearchHit(**hit) for hit in hits])


@router.post("/augment", response_model=AugmentResponse, summary="Готовый RAG-prompt")
async def augment(payload: AugmentRequest) -> AugmentResponse:
    _check_enabled()
    service = get_rag_service()
    prompt = await service.augment_prompt(
        query=payload.query,
        system_prompt=payload.system_prompt,
        top_k=payload.top_k,
        namespace=payload.namespace,
    )
    return AugmentResponse(prompt=prompt)


@router.delete("/{doc_id}", summary="Удалить chunk по id")
async def delete(doc_id: str) -> dict[str, bool]:
    _check_enabled()
    service = get_rag_service()
    ok = await service.delete(doc_id)
    return {"deleted": ok}


@router.get("/stats", response_model=StatsResponse, summary="Состояние индекса")
async def stats() -> StatsResponse:
    if not rag_settings.enabled:
        return StatsResponse(
            enabled=False,
            backend=rag_settings.vector_backend,
            embedding_provider=rag_settings.embedding_provider,
            count=0,
        )
    service = get_rag_service()
    count = await service.count()
    return StatsResponse(
        enabled=True,
        backend=rag_settings.vector_backend,
        embedding_provider=rag_settings.embedding_provider,
        count=count,
    )
