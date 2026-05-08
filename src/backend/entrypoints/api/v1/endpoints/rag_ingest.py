"""RAG ingest endpoints (К4 MVP, Шаг 8).

* ``POST /rag/ingest/start`` — multipart upload N файлов.
* ``GET /rag/ingest/status/{task_id}`` — текущее состояние задачи.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.backend.services.ai.rag_ingest_service import get_rag_ingest_service

__all__ = ("router",)

router = APIRouter()


@router.post("/ingest/start", summary="Загрузить N файлов в RAG-индекс")
async def start_rag_ingest(
    files: list[UploadFile] = File(...),
    collection: str = Form(default="default"),
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
    state = service.status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task_id не найден.")
    return state
