"""AI Feedback Loop — хранение, разметка и индексация ответов AI-агентов.

Пакет собирает полный цикл обратной связи по ответам AI:
  * ``AIFeedbackDoc`` — модель документа ответа (Pydantic);
  * ``FeedbackRepository`` — протокол хранилища (абстракция над БД);
  * ``InMemoryFeedbackRepository`` — реализация для Wave 4 (in-memory,
    будет заменена на MongoDB/Postgres в Wave 9);
  * ``AIFeedbackService`` — сервис разметки ответов оператором;
  * ``FeedbackIndexer`` — оркестратор перевода размеченных ответов
    в RAG-индекс (через ``RAGService``).

Используется ``AIAgentService`` для автосохранения каждого ответа
и DSL-процессором ``GetFeedbackExamplesProcessor`` для few-shot
промптинга из подтверждённых реальных примеров.
"""

from __future__ import annotations

from src.services.ai.feedback.feedback_indexer import (
    FeedbackIndexer,
    FeedbackIndexResult,
    get_feedback_indexer,
)
from src.services.ai.feedback.feedback_service import (
    AIFeedbackService,
    get_ai_feedback_service,
)
from src.services.ai.feedback.models import AIFeedbackDoc, FeedbackLabel
from src.services.ai.feedback.repository import (
    FeedbackRepository,
    InMemoryFeedbackRepository,
    get_feedback_repository,
)

__all__ = (
    "AIFeedbackDoc",
    "AIFeedbackService",
    "FeedbackIndexResult",
    "FeedbackIndexer",
    "FeedbackLabel",
    "FeedbackRepository",
    "InMemoryFeedbackRepository",
    "get_ai_feedback_service",
    "get_feedback_indexer",
    "get_feedback_repository",
)
