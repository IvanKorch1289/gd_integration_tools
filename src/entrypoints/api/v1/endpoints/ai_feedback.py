"""AI Feedback API — разметка ответов AI-агентов и перевод в RAG.

Предоставляет оператору HTTP-интерфейс к ``AIFeedbackService``
и ``FeedbackIndexer``:

  * ``GET  /pending``               — ответы, ожидающие разметки;
  * ``GET  /labeled``               — размеченные ответы;
  * ``GET  /stats``                 — счётчики по меткам и индексации;
  * ``GET  /{doc_id}``              — подробности одного ответа;
  * ``POST /{doc_id}/label``        — проставить метку;
  * ``POST /index-to-rag``          — ручной запуск индексации в RAG.

Все эндпоинты возвращают JSON; ошибки — стандартный FastAPI detail.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.services.ai.feedback import get_ai_feedback_service, get_feedback_indexer

__all__ = ("router",)

router = APIRouter()


class LabelRequest(BaseModel):
    """Запрос на разметку одного ответа AI-агента."""

    label: Literal["positive", "negative", "skip"] = Field(
        description="Метка оператора."
    )
    comment: str | None = Field(default=None, description="Комментарий.")
    operator_id: str | None = Field(
        default=None, description="Идентификатор оператора для аудита."
    )


class IndexRequest(BaseModel):
    """Запрос на перевод размеченных ответов в RAG-индекс."""

    agent_id: str | None = Field(
        default=None, description="Фильтр по агенту; null — все."
    )
    limit: int = Field(
        default=100, ge=1, le=1000, description="Максимум документов за один запуск."
    )


def _doc_to_dict(doc: Any) -> dict[str, Any]:
    """Сериализует ``AIFeedbackDoc`` в dict (для JSON-ответа).

    Args:
        doc: Документ ``AIFeedbackDoc`` либо ``None``.

    Returns:
        Словарь с ISO-форматированием дат.
    """
    return doc.model_dump(mode="json") if doc else {}


@router.get("/pending", summary="Ответы, ожидающие разметки")
async def list_pending(
    agent_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Возвращает ответы агентов без проставленной метки.

    Args:
        agent_id: Фильтр по идентификатору агента.
        limit: Размер страницы.
        offset: Смещение пагинации.

    Returns:
        ``{"items": [...], "total": N}``.
    """
    service = get_ai_feedback_service()
    items = await service.list_pending(agent_id=agent_id, limit=limit, offset=offset)
    return {"items": [_doc_to_dict(d) for d in items], "total": len(items)}


@router.get("/labeled", summary="Размеченные ответы")
async def list_labeled(
    label: Literal["positive", "negative", "skip"] | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    indexed_in_rag: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Возвращает размеченные ответы с комбинированным фильтром.

    Args:
        label: Фильтр по метке.
        agent_id: Фильтр по агенту.
        indexed_in_rag: Фильтр по статусу индексации.
        limit: Размер страницы.
        offset: Смещение.

    Returns:
        ``{"items": [...], "total": N}``.
    """
    service = get_ai_feedback_service()
    items = await service.list_labeled(
        label=label,
        agent_id=agent_id,
        indexed_in_rag=indexed_in_rag,
        limit=limit,
        offset=offset,
    )
    return {"items": [_doc_to_dict(d) for d in items], "total": len(items)}


@router.get("/stats", summary="Статистика feedback")
async def feedback_stats() -> dict[str, int]:
    """Возвращает агрегированные счётчики по меткам.

    Returns:
        ``{"pending": N, "positive": N, "negative": N, "skip": N, "indexed": N}``.
    """
    service = get_ai_feedback_service()
    return await service.stats()


@router.get("/{doc_id}", summary="Подробности ответа")
async def get_doc(doc_id: str) -> dict:
    """Возвращает документ ответа по идентификатору.

    Args:
        doc_id: Идентификатор документа.

    Returns:
        JSON-представление документа.

    Raises:
        HTTPException: 404, если документ не найден.
    """
    service = get_ai_feedback_service()
    doc = await service.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Feedback {doc_id!r} not found")
    return _doc_to_dict(doc)


@router.post("/{doc_id}/label", summary="Проставить метку обратной связи")
async def label_doc(doc_id: str, payload: LabelRequest) -> dict:
    """Сохраняет метку оператора для ответа.

    Args:
        doc_id: Идентификатор документа.
        payload: Тело запроса с меткой и комментарием.

    Returns:
        Обновлённый документ.

    Raises:
        HTTPException: 404, если документ не найден.
    """
    service = get_ai_feedback_service()
    try:
        updated = await service.set_feedback(
            doc_id=doc_id,
            label=payload.label,
            comment=payload.comment,
            operator_id=payload.operator_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _doc_to_dict(updated)


@router.post("/index-to-rag", summary="Перевести размеченные ответы в RAG-индекс")
async def index_to_rag(payload: IndexRequest | None = None) -> dict:
    """Запускает индексацию размеченных ответов в RAG.

    Args:
        payload: Параметры (опционально). Если отсутствует —
            индексируются все агенты, limit=100.

    Returns:
        Счётчики результата (``indexed_positive``, ``errors`` и т.д.).
    """
    indexer = get_feedback_indexer()
    agent_id = payload.agent_id if payload else None
    limit = payload.limit if payload else 100
    result = await indexer.index_batch(agent_id=agent_id, limit=limit)
    return result.as_dict()
