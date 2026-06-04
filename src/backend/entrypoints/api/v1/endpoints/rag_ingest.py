"""RAG ingest endpoints (К4 MVP, Шаг 8; обновлено в Wave D.2).

* ``POST /rag/ingest/start`` — multipart upload N файлов.
* ``GET /rag/ingest/status/{task_id}`` — текущее состояние задачи (async).
* ``GET /rag/ingest/recent`` — последние N задач (D.2).
* ``POST /rag/bulk-ingest`` — bulk ingest списка {content, metadata} документов (S19 K4 W1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.backend.core.config.features import feature_flags
from src.backend.services.ai.rag_ingest_service import get_rag_ingest_service

__all__ = ("router",)

router = APIRouter()


@router.post("/ingest/start", summary="Загрузить N файлов в RAG-индекс")
async def start_rag_ingest(
    files: list[UploadFile] = File(...), collection: str = Form(default="default")
) -> dict[str, Any]:
    """Принимает multipart-uploads и стартует ingest."""
    if not files:
        raise HTTPException(status_code=400, detail="Не передано ни одного файла.")
    pairs = [(f.filename or "file", await f.read()) for f in files]
    service = get_rag_ingest_service()
    return await service.ingest(pairs, collection=collection)


@router.get("/ingest/status/{task_id}", summary="Статус ingest-задачи")
async def get_rag_ingest_status(task_id: str) -> dict[str, Any]:
    """Возвращает текущее состояние ingest-задачи."""
    service = get_rag_ingest_service()
    state = await service.status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task_id не найден.")
    return state


@router.get("/ingest/recent", summary="Последние ingest-задачи (D.2)")
async def list_recent_ingests(
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Возвращает последние ``limit`` ingest-задач (newest first)."""
    service = get_rag_ingest_service()
    items = await service.list_recent(limit=limit)
    return {"items": items, "count": len(items)}


# ─── S19 K4 W1: Bulk RAG ingest ──────────────────────────────────────────────


class BulkDocument(BaseModel):
    """Схема одного документа для bulk ingest."""

    content: str = Field(..., description="Текстовый контент документа")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Метаданные документа"
    )


class BulkIngestRequest(BaseModel):
    """Request body для POST /rag/bulk-ingest."""

    documents: list[BulkDocument] = Field(
        ..., min_length=1, description="Список документов"
    )
    collection: str = Field(default="default", description="Namespace RAG collection")


@router.post(
    "/bulk-ingest",
    summary="Bulk ingest документов в RAG (S19 K4 W1)",
    responses={
        200: {"description": "Bulk ingest запущен, результаты returned sync"},
        400: {"description": "Пустой список документов"},
        403: {"description": "Feature flag multipart_rag_ingest выключен"},
    },
)
async def bulk_rag_ingest(request: BulkIngestRequest) -> dict[str, Any]:
    """Bulk ingest списка {content, metadata} документов.

    Обрабатывает каждый документ через embeddings pipeline и сохраняет в Chroma.
    Работает синхронно (not deferred) — ожидает завершения всех ingests.

    Feature flag: ``multipart_rag_ingest`` должен быть включён.
    """
    if not feature_flags.multipart_rag_ingest:
        raise HTTPException(
            status_code=403,
            detail="Feature flag multipart_rag_ingest выключен. "
            "Установите FEATURE_MULTIPART_RAG_INGEST=true для активации.",
        )

    if not request.documents:
        raise HTTPException(status_code=400, detail="Список документов пуст.")

    service = get_rag_ingest_service()
    rag = service._ensure_rag()

    task_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": "running",
        "total": len(request.documents),
        "processed": 0,
        "doc_ids": [],
        "errors": [],
        "collection": request.collection,
        "started_at": datetime.now(UTC).isoformat(),
    }

    for doc in request.documents:
        try:
            doc_id = await rag.ingest(
                doc.content, metadata=doc.metadata, namespace=request.collection
            )
            payload["doc_ids"].append(doc_id)
        except Exception as exc:
            payload["errors"].append(
                {"content_preview": doc.content[:100], "error": str(exc)}
            )
        payload["processed"] += 1

    payload["status"] = (
        "completed" if not payload["errors"] else "completed_with_errors"
    )
    payload["finished_at"] = datetime.now(UTC).isoformat()

    return payload
