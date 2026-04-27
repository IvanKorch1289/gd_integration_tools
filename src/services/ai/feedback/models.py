"""Модели AI Feedback Loop.

Определяет Pydantic-документы, описывающие ответ AI-агента,
его разметку оператором и статус перевода в RAG-индекс.

Модели агностичны к хранилищу (in-memory сейчас, MongoDB/Postgres
в Wave 9) — используются и сервисом, и репозиторием.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("AIFeedbackDoc", "FeedbackLabel")


FeedbackLabel = Literal["positive", "negative", "skip"]


def _utc_now() -> datetime:
    """Возвращает текущее UTC-время с явным tz-aware таймзоны.

    Returns:
        Текущий момент в UTC.
    """
    return datetime.now(timezone.utc)


class AIFeedbackDoc(BaseModel):
    """Документ ответа AI-агента с состоянием разметки оператором.

    Хранит полный контекст вызова агента (запрос, ответ, метаданные)
    и жизненный цикл разметки: ожидание → оценка → перевод в RAG.

    Атрибуты:
        id: Уникальный идентификатор записи (UUID4 hex).
        query: Исходный запрос пользователя.
        response: Текст ответа агента.
        agent_id: Идентификатор агента (для фильтрации в UI).
        session_id: Идентификатор сессии, если есть.
        feedback: Метка оператора; ``None`` — ожидает разметки.
        feedback_comment: Пояснение оператора при разметке.
        operator_id: Идентификатор оператора (для аудита).
        indexed_in_rag: Переведён ли ответ в RAG-индекс.
        rag_doc_id: Идентификатор документа в RAG (после индексации).
        metadata: Дополнительные данные (tenant_id, user_id и т.д.).
        created_at: Момент создания записи.
        labeled_at: Момент разметки оператором.
        indexed_at: Момент индексации в RAG.
    """

    model_config = ConfigDict(extra="ignore", frozen=False)

    id: str = Field(default_factory=lambda: uuid4().hex)
    query: str
    response: str
    agent_id: str
    session_id: str | None = None
    feedback: FeedbackLabel | None = None
    feedback_comment: str | None = None
    operator_id: str | None = None
    indexed_in_rag: bool = False
    rag_doc_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    labeled_at: datetime | None = None
    indexed_at: datetime | None = None
