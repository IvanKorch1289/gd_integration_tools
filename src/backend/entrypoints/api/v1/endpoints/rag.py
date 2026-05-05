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

import logging
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from src.backend.core.config.rag import rag_settings
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.services.ai.document_parsers import parse_document, sniff_mime
from src.backend.services.ai.rag_service import get_rag_service

logger = logging.getLogger(__name__)

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
    collection: str | None = Field(
        default=None, description="Если задан — count в рамках namespace."
    )


class StatsQuery(BaseModel):
    """Query-параметры /stats."""

    collection: str | None = Field(
        default=None, description="Опциональный namespace для статистики."
    )


class DeleteResponse(BaseModel):
    """Ответ /delete."""

    deleted: bool


class DocIdPath(BaseModel):
    """Path-параметр идентификатора документа."""

    doc_id: str = Field(..., description="ID документа (sha256 prefix).")


class CollectionNamePath(BaseModel):
    """Path-параметр для namespace (имени коллекции)."""

    name: str = Field(..., min_length=1, description="Имя namespace.")


class DeleteCollectionResponse(BaseModel):
    """Ответ DELETE /collections/{name}."""

    namespace: str
    deleted: int = Field(..., description="Количество удалённых chunks.")


class CollectionStatsResponse(BaseModel):
    """Ответ GET /collections/{name}."""

    namespace: str
    count: int
    exists: bool


class UploadResponse(BaseModel):
    """Ответ POST /upload."""

    doc_id: str
    chunks: int
    mime: str
    size_bytes: int
    extraction_warnings: list[str] = Field(default_factory=list)


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
            query=query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
        )
        return AugmentResponse(prompt=prompt)

    async def delete(self, *, doc_id: str) -> DeleteResponse:
        _check_enabled()
        ok = await get_rag_service().delete(doc_id)
        return DeleteResponse(deleted=ok)

    async def stats(self, *, collection: str | None = None) -> StatsResponse:
        if not rag_settings.enabled:
            return StatsResponse(
                enabled=False,
                backend=rag_settings.vector_backend,
                embedding_provider=rag_settings.embedding_provider,
                count=0,
                collection=collection,
            )
        count = await get_rag_service().count(collection=collection)
        return StatsResponse(
            enabled=True,
            backend=rag_settings.vector_backend,
            embedding_provider=rag_settings.embedding_provider,
            count=count,
            collection=collection,
        )

    async def delete_collection(self, *, name: str) -> DeleteCollectionResponse:
        _check_enabled()
        deleted = await get_rag_service().delete_collection(name)
        return DeleteCollectionResponse(namespace=name, deleted=deleted)

    async def collection_stats(self, *, name: str) -> CollectionStatsResponse:
        _check_enabled()
        info = await get_rag_service().get_collection_stats(name)
        return CollectionStatsResponse(**info)

    async def upload(
        self,
        *,
        file: UploadFile,
        namespace: str = "default",
        metadata_json: str | None = None,
    ) -> UploadResponse:
        """Multipart-upload: парсит PDF/DOCX/MD/TXT → ingest в RAG."""
        _check_enabled()

        raw = await file.read()
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Файл пустой."
            )
        mime = sniff_mime(file.filename, file.content_type)
        try:
            text, parse_meta = await parse_document(raw, mime, filename=file.filename)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            ) from exc

        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Не удалось извлечь текст из файла.",
            )

        meta: dict[str, Any] = {"source": "upload"}
        if file.filename:
            meta["filename"] = file.filename
        if metadata_json:
            import json

            try:
                user_meta = json.loads(metadata_json)
                if isinstance(user_meta, dict):
                    meta.update(user_meta)
            except json.JSONDecodeError:
                logger.warning("rag_upload: metadata_json invalid, ignored")

        rag = get_rag_service()
        doc_id = await rag.ingest(content=text, metadata=meta, namespace=namespace)
        chunks = len(rag.chunk_text(text))
        return UploadResponse(
            doc_id=doc_id,
            chunks=chunks,
            mime=parse_meta["mime"],
            size_bytes=parse_meta["size_bytes"],
            extraction_warnings=list(parse_meta.get("warnings") or []),
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
            summary="Состояние индекса (опционально по namespace)",
            service_getter=_get_facade,
            service_method="stats",
            query_model=StatsQuery,
            response_model=StatsResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_collection_stats",
            method="GET",
            path="/collections/{name}",
            summary="Статистика по namespace",
            service_getter=_get_facade,
            service_method="collection_stats",
            path_model=CollectionNamePath,
            response_model=CollectionStatsResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="rag_delete_collection",
            method="DELETE",
            path="/collections/{name}",
            summary="Удалить все chunks из namespace",
            service_getter=_get_facade,
            service_method="delete_collection",
            path_model=CollectionNamePath,
            response_model=DeleteCollectionResponse,
            tags=common_tags,
        ),
    ]
)


# Multipart /upload не вписывается в декларативный ActionSpec
# (ожидает pydantic body); регистрируем вручную.
@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Загрузить файл (PDF/DOCX/MD/TXT) и проиндексировать",
    tags=list(common_tags),
)
async def rag_upload(
    file: Annotated[UploadFile, File(description="PDF/DOCX/MD/TXT.")],
    namespace: Annotated[str, Form()] = "default",
    metadata_json: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    """Принимает multipart-файл, парсит, шардирует и грузит в RAG."""
    return await _FACADE.upload(
        file=file, namespace=namespace, metadata_json=metadata_json
    )
