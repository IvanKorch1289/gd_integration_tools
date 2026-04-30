"""RAG API — публичный CRUD к ``RAGService``.

W26.5: маршруты регистрируются декларативно через ActionSpec.

* ``POST /ingest``    — загрузить документ (chunking + embedding + upsert).
* ``POST /search``    — семантический поиск top-k.
* ``POST /augment``   — подтянуть контекст и вернуть готовый prompt.
* ``DELETE /{doc_id}`` — удалить chunks по id.
* ``GET  /stats``     — количество документов в store.

Если ``rag_settings.enabled=False`` — модифицирующие endpoints возвращают
503; ``/stats`` отдаёт agg-объект с ``enabled=False`` без обращения к
бэкенду.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.core.config.rag import rag_settings
from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.ai.rag_service import get_rag_service

__all__ = ("router",)


# --- Schemas ---------------------------------------------------------------


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
    """Ответ /ingest."""

    doc_id: str = Field(..., description="Идентификатор документа (sha256 prefix).")


class SearchRequest(BaseModel):
    """Запрос /search."""

    query: str = Field(..., min_length=1, description="Поисковый запрос.")
    top_k: int = Field(default=5, ge=1, le=100)
    namespace: str | None = Field(default=None)


class SearchHit(BaseModel):
    """Один результат поиска."""

    id: str
    document: str
    metadata: dict[str, Any]
    distance: float


class SearchResponse(BaseModel):
    """Список найденных документов."""

    items: list[SearchHit]


class AugmentRequest(BaseModel):
    """Запрос /augment."""

    query: str = Field(..., min_length=1)
    system_prompt: str = Field(default="", description="Системная инструкция.")
    top_k: int = Field(default=5, ge=1, le=100)
    namespace: str | None = Field(default=None)


class AugmentResponse(BaseModel):
    """Готовый prompt с RAG-контекстом."""

    prompt: str = Field(..., description="Готовый prompt с RAG-контекстом.")


class StatsResponse(BaseModel):
    """Состояние индекса."""

    enabled: bool
    backend: str
    embedding_provider: str
    count: int


class DeleteResponse(BaseModel):
    """Ответ /delete."""

    deleted: bool


class DocIdPath(BaseModel):
    """Path-параметр идентификатора документа."""

    doc_id: str = Field(..., description="ID документа (sha256 prefix).")


# --- Helpers ---------------------------------------------------------------


def _check_enabled() -> None:
    if not rag_settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG отключён (rag_settings.enabled=False).",
        )


# --- Service facade --------------------------------------------------------


class _RAGFacade:
    """Адаптер над ``RAGService`` с проверкой rag_settings.enabled."""

    async def ingest(
        self,
        *,
        content: str,
        namespace: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestResponse:
        _check_enabled()
        doc_id = await get_rag_service().ingest(
            content=content, metadata=metadata, namespace=namespace
        )
        return IngestResponse(doc_id=doc_id)

    async def search(
        self, *, query: str, top_k: int = 5, namespace: str | None = None
    ) -> SearchResponse:
        _check_enabled()
        hits = await get_rag_service().search(
            query=query, top_k=top_k, namespace=namespace
        )
        return SearchResponse(items=[SearchHit(**hit) for hit in hits])

    async def augment(
        self,
        *,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> AugmentResponse:
        _check_enabled()
        prompt = await get_rag_service().augment_prompt(
            query=query,
            system_prompt=system_prompt,
            top_k=top_k,
            namespace=namespace,
        )
        return AugmentResponse(prompt=prompt)

    async def delete(self, *, doc_id: str) -> DeleteResponse:
        _check_enabled()
        ok = await get_rag_service().delete(doc_id)
        return DeleteResponse(deleted=ok)

    async def stats(self) -> StatsResponse:
        if not rag_settings.enabled:
            return StatsResponse(
                enabled=False,
                backend=rag_settings.vector_backend,
                embedding_provider=rag_settings.embedding_provider,
                count=0,
            )
        count = await get_rag_service().count()
        return StatsResponse(
            enabled=True,
            backend=rag_settings.vector_backend,
            embedding_provider=rag_settings.embedding_provider,
            count=count,
        )


_FACADE = _RAGFacade()


def _get_facade() -> _RAGFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("RAG",)


builder.add_actions(
    [
        ActionSpec(
            name="rag_ingest",
            method="POST",
            path="/ingest",
            summary="Загрузить документ",
            service_getter=_get_facade,
            service_method="ingest",
            body_model=IngestRequest,
            response_model=IngestResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_search",
            method="POST",
            path="/search",
            summary="Семантический поиск",
            service_getter=_get_facade,
            service_method="search",
            body_model=SearchRequest,
            response_model=SearchResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_augment",
            method="POST",
            path="/augment",
            summary="Готовый RAG-prompt",
            service_getter=_get_facade,
            service_method="augment",
            body_model=AugmentRequest,
            response_model=AugmentResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_delete",
            method="DELETE",
            path="/{doc_id}",
            summary="Удалить chunk по id",
            service_getter=_get_facade,
            service_method="delete",
            path_model=DocIdPath,
            response_model=DeleteResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_stats",
            method="GET",
            path="/stats",
            summary="Состояние индекса",
            service_getter=_get_facade,
            service_method="stats",
            response_model=StatsResponse,
            tags=common_tags,
        ),
    ]
)
