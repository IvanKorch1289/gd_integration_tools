"""AI Feedback API — разметка ответов AI-агентов и перевод в RAG.

W26.5: маршруты регистрируются декларативно через ActionSpec;
прямых ``@router.{get,post}`` нет.

Эндпоинты под ``/api/v1/ai/feedback/*``:

  * ``GET  /pending``         — ответы, ожидающие разметки;
  * ``GET  /labeled``         — размеченные ответы;
  * ``GET  /stats``           — счётчики по меткам и индексации;
  * ``GET  /{doc_id}``        — подробности одного ответа;
  * ``POST /{doc_id}/label``  — проставить метку;
  * ``POST /index-to-rag``    — ручной запуск индексации в RAG.

Все эндпоинты возвращают JSON; ошибки — стандартный FastAPI detail.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.ai.feedback import get_ai_feedback_service, get_feedback_indexer

__all__ = ("router",)


# --- Body schemas ----------------------------------------------------------


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


# --- Path / Query schemas --------------------------------------------------


class DocIdPath(BaseModel):
    """Path-параметр идентификатора feedback-документа."""

    doc_id: str = Field(..., description="ID документа AIFeedbackDoc.")


class PendingQuery(BaseModel):
    """Query для list_pending."""

    agent_id: str | None = Field(default=None, description="Фильтр по агенту.")
    limit: int = Field(default=50, ge=1, le=200, description="Размер страницы.")
    offset: int = Field(default=0, ge=0, description="Смещение пагинации.")


class LabeledQuery(BaseModel):
    """Query для list_labeled."""

    label: Literal["positive", "negative", "skip"] | None = Field(
        default=None, description="Фильтр по метке."
    )
    agent_id: str | None = Field(default=None, description="Фильтр по агенту.")
    indexed_in_rag: bool | None = Field(
        default=None, description="Фильтр по статусу индексации."
    )
    limit: int = Field(default=100, ge=1, le=500, description="Размер страницы.")
    offset: int = Field(default=0, ge=0, description="Смещение пагинации.")


# --- Helpers ---------------------------------------------------------------


def _doc_to_dict(doc: Any) -> dict[str, Any]:
    """Сериализует AIFeedbackDoc → dict (для JSON-ответа)."""
    return doc.model_dump(mode="json") if doc else {}


def _list_response_handler(
    result: list[Any], _: dict[str, Any]
) -> dict[str, Any]:
    """list[doc] → ``{"items": [...], "total": N}``."""
    return {"items": [_doc_to_dict(d) for d in result], "total": len(result)}


def _get_doc_handler(result: Any | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """doc → dict; 404 если None."""
    if result is None:
        doc_id = kwargs.get("doc_id")
        raise HTTPException(status_code=404, detail=f"Feedback {doc_id!r} not found")
    return _doc_to_dict(result)


def _label_doc_handler(result: Any, _: dict[str, Any]) -> dict[str, Any]:
    """Обёртка над dict — успех."""
    return _doc_to_dict(result)


def _index_result_handler(result: Any, _: dict[str, Any]) -> dict[str, int]:
    """IndexResult → dict через as_dict()."""
    return result.as_dict()


# --- Service facade --------------------------------------------------------


class _AIFeedbackFacade:
    """Адаптер над ``AIFeedbackService`` для action-маршрутов.

    Нужен, чтобы ловить ``KeyError`` из ``set_feedback`` и пробрасывать
    как HTTP 404 (legacy-поведение). ``ActionRouterBuilder`` не имеет
    встроенного маппинга исключений, поэтому обёртка живёт здесь.
    """

    async def list_pending(
        self, *, agent_id: str | None, limit: int, offset: int
    ) -> list[Any]:
        return await get_ai_feedback_service().list_pending(
            agent_id=agent_id, limit=limit, offset=offset
        )

    async def list_labeled(
        self,
        *,
        label: Literal["positive", "negative", "skip"] | None,
        agent_id: str | None,
        indexed_in_rag: bool | None,
        limit: int,
        offset: int,
    ) -> list[Any]:
        return await get_ai_feedback_service().list_labeled(
            label=label,
            agent_id=agent_id,
            indexed_in_rag=indexed_in_rag,
            limit=limit,
            offset=offset,
        )

    async def stats(self) -> dict[str, int]:
        return await get_ai_feedback_service().stats()

    async def get(self, *, doc_id: str) -> Any | None:
        return await get_ai_feedback_service().get(doc_id)

    async def label(
        self,
        *,
        doc_id: str,
        label: Literal["positive", "negative", "skip"],
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> Any:
        try:
            return await get_ai_feedback_service().set_feedback(
                doc_id=doc_id,
                label=label,
                comment=comment,
                operator_id=operator_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def index_batch(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> Any:
        return await get_feedback_indexer().index_batch(
            agent_id=agent_id, limit=limit
        )


_FACADE = _AIFeedbackFacade()


def _get_facade() -> _AIFeedbackFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("AI · Feedback",)


builder.add_actions(
    [
        ActionSpec(
            name="list_pending_feedback",
            method="GET",
            path="/pending",
            summary="Ответы, ожидающие разметки",
            service_getter=_get_facade,
            service_method="list_pending",
            query_model=PendingQuery,
            response_handler=_list_response_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="list_labeled_feedback",
            method="GET",
            path="/labeled",
            summary="Размеченные ответы",
            service_getter=_get_facade,
            service_method="list_labeled",
            query_model=LabeledQuery,
            response_handler=_list_response_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="feedback_stats",
            method="GET",
            path="/stats",
            summary="Статистика feedback",
            service_getter=_get_facade,
            service_method="stats",
            tags=common_tags,
        ),
        ActionSpec(
            name="get_feedback_doc",
            method="GET",
            path="/{doc_id}",
            summary="Подробности ответа",
            service_getter=_get_facade,
            service_method="get",
            path_model=DocIdPath,
            response_handler=_get_doc_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="label_feedback_doc",
            method="POST",
            path="/{doc_id}/label",
            summary="Проставить метку обратной связи",
            service_getter=_get_facade,
            service_method="label",
            path_model=DocIdPath,
            body_model=LabelRequest,
            response_handler=_label_doc_handler,
            tags=common_tags,
        ),
        ActionSpec(
            name="index_feedback_to_rag",
            method="POST",
            path="/index-to-rag",
            summary="Перевести размеченные ответы в RAG-индекс",
            service_getter=_get_facade,
            service_method="index_batch",
            body_model=IndexRequest,
            response_handler=_index_result_handler,
            tags=common_tags,
        ),
    ]
)
