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

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from src.backend.core.config.rag import rag_settings
from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.entrypoints.dependencies.rate_limit import get_default_rate_limiter
from src.backend.services.ai.document_parsers import parse_document, sniff_mime
from src.backend.services.ai.rag_ingest_service import get_rag_ingest_service
from src.backend.services.ai.rag_service import get_rag_service

logger = get_logger(__name__)

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


class CitationItem(BaseModel):
    """Одна цитата из RAG-контекста (Stream E.5).

    Используется для traceability: какие chunks RAG использовал для
    обогащения промпта. Поля совпадают с :class:`RAGCitation`
    (``services/ai/rag_service.py``).
    """

    source_doc: str = Field(..., description="ID исходного документа.")
    chunk_id: str = Field(..., description="ID chunk'а в vector store.")
    score: float = Field(..., description="Distance / score (lower = closer).")
    chunk_idx: int | None = Field(default=None)
    namespace: str | None = Field(default=None)


class AugmentResponse(BaseModel):
    """Готовый prompt с RAG-контекстом + citations."""

    prompt: str = Field(..., description="Готовый prompt с RAG-контекстом.")
    citations: list[CitationItem] = Field(
        default_factory=list,
        description="Цитаты — какие chunks использовались для обогащения.",
    )


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
    engine: str = Field(
        default="legacy", description="Использованный парсер: 'markitdown' | 'legacy'."
    )
    markdown: bool = Field(
        default=False,
        description="True, если извлечённый текст — Markdown (markitdown-engine).",
    )
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
    """Адаптер над ``RagIngestService`` (single-doc) с проверкой rag_settings.enabled.

    Single-doc endpoint'ы (``POST /ingest``, ``POST /upload``) маршрутизируются
    через :meth:`RagIngestService.ingest_text` — это даёт единый путь с bulk
    ingest'ом и применяет ``_maybe_mask_pii`` (Block 1.3, ADR-0072) до записи
    в vector store.
    """

    async def ingest(
        self,
        *,
        content: str,
        namespace: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestResponse:
        """Ingest документа в RAG-хранилище с заданным namespace.

        D-A9-01 fix (cycle 1): PII fail-CLOSED contract на single-doc API.
        ``_maybe_mask_pii`` применяется перед ingest. При sanitizer
        failure → ``PIIFailClosedError`` → ``HTTPException(503)``.
        Raw PII НЕ пишется в vector store (production safety).
        Feature-flag ``RAG_INGEST_PII_FAIL_OPEN=true`` (только dev_light)
        → log warning + skip mask (raw text уходит в vector store).
        """
        from src.backend.core.config import ai_stack
        from src.backend.core.policy.pii_fail_closed import (
            PIIFailClosedError,
            raise_pii_fail_closed,
        )
        from src.backend.services.ai.rag_ingest_service import _maybe_mask_pii

        _check_enabled()

        # D-A9-01 fix (cycle 1): explicit PII mask с fail-CLOSED contract.
        settings = ai_stack.rag_ingest_settings
        pii_fail_open = bool(getattr(settings, "pii_fail_open", False))

        try:
            masked_content, pii_meta = _maybe_mask_pii(content)
            metadata_with_pii = {**(metadata or {}), **pii_meta}
        except PIIFailClosedError as exc:
            if pii_fail_open:
                # D-A9-01 fix (cycle 1, opt-in): dev_light only.
                logger.warning(
                    "rag.ingest: pii_fail_open=True, skipping mask (sanitizer: %s)",
                    exc.__cause__ or exc,
                )
                metadata_with_pii = {
                    **(metadata or {}),
                    "pii_masked": False,
                    "pii_mask_skipped": True,
                }
                masked_content = content  # raw text
            else:
                # Production: fail-CLOSED. Surface as 503.
                logger.error("rag.ingest: PII redaction failed: %s", exc)
                raise_pii_fail_closed(
                    source="rag.ingest", payload_size=len(content), exc=exc
                )

        doc_id = await get_rag_service().ingest(
            content=masked_content, metadata=metadata_with_pii, namespace=namespace
        )
        return IngestResponse(doc_id=doc_id)

    async def search(
        self, *, query: str, top_k: int = 5, namespace: str | None = None
    ) -> SearchResponse:
        """Поиск релевантных chunks по запросу в указанном namespace."""
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
        """Augment prompt контекстом из RAG с citations для LLM."""
        _check_enabled()
        result = await get_rag_service().augment_prompt_with_citations(
            query=query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
        )
        return AugmentResponse(
            prompt=result.prompt,
            citations=[
                CitationItem(
                    source_doc=c.source_doc,
                    chunk_id=c.chunk_id,
                    score=c.score,
                    chunk_idx=c.chunk_idx,
                    namespace=c.namespace,
                )
                for c in result.citations
            ],
        )

    async def delete(self, *, doc_id: str) -> DeleteResponse:
        """Удалить документ из RAG-хранилища по doc_id."""
        _check_enabled()
        ok = await get_rag_service().delete(doc_id)
        return DeleteResponse(deleted=ok)

    async def stats(self, *, collection: str | None = None) -> StatsResponse:
        """Получить статистику RAG (количество документов, backend, provider)."""
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
        """Multipart-upload: парсит PDF/DOCX/MD/TXT → ingest в RAG.

        Текст из файла прогоняется через :meth:`RagIngestService.ingest_text`
        (PII-mask + provenance). Подсчёт chunks для ответа выполняется
        отдельным вызовом ``RAGService.chunk_text`` (read-only операция).
        """
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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,  # starlette 1.3.0+
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
        ingest_svc = get_rag_ingest_service()
        doc_id = await ingest_svc.ingest_text(
            content=text, filename=file.filename, namespace=namespace, metadata=meta
        )
        chunks = len(rag.chunk_text(text))
        return UploadResponse(
            doc_id=doc_id,
            chunks=chunks,
            mime=parse_meta["mime"],
            size_bytes=parse_meta["size_bytes"],
            engine=str(parse_meta.get("engine") or "legacy"),
            markdown=bool(parse_meta.get("markdown") or False),
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
    summary="Загрузить файл (PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON/MD/TXT) и проиндексировать",
    tags=list(common_tags),
)
async def rag_upload(
    file: Annotated[
        UploadFile, File(description="PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON/MD/TXT.")
    ],
    namespace: Annotated[str, Form()] = "default",
    metadata_json: Annotated[str | None, Form()] = None,
    _rate_limit: None = Depends(get_default_rate_limiter()),
) -> UploadResponse:
    """Принимает multipart-файл, парсит, шардирует и грузит в RAG."""
    return await _FACADE.upload(
        file=file, namespace=namespace, metadata_json=metadata_json
    )
