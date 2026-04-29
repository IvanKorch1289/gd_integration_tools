"""FeedbackIndexer — перевод размеченных ответов AI в RAG-индекс.

Оркестратор читает из ``FeedbackRepository`` документы со статусом
``indexed_in_rag=False`` и переносит их в RAG через ``RAGService.ingest``:
  * ``skip`` — игнорируется (в индекс не попадает);
  * ``positive`` / ``negative`` — индексируется с меткой в metadata
    для фильтрации при поиске (few-shot prompting).

После успешной индексации в документе обновляются поля
``indexed_in_rag=True``, ``rag_doc_id``, ``indexed_at``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.core.di import app_state_singleton
from src.services.ai.feedback.models import AIFeedbackDoc
from src.services.ai.feedback.repository import (
    FeedbackRepository,
    get_feedback_repository,
)

__all__ = ("FeedbackIndexResult", "FeedbackIndexer", "get_feedback_indexer")

logger = logging.getLogger("services.ai.feedback.indexer")


def _utc_now() -> datetime:
    """Возвращает текущий момент в UTC (aware)."""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class FeedbackIndexResult:
    """Результат работы ``FeedbackIndexer.index_batch``.

    Атрибуты:
        indexed_positive: Сколько ``positive``-документов переведено в RAG.
        indexed_negative: Сколько ``negative``-документов переведено в RAG.
        skipped: Сколько ``skip``-документов пропущено.
        errors: Сколько документов не удалось проиндексировать.
    """

    indexed_positive: int = 0
    indexed_negative: int = 0
    skipped: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        """Сериализует результат в dict для JSON-ответа.

        Returns:
            Словарь с полями-счётчиками.
        """
        return {
            "indexed_positive": self.indexed_positive,
            "indexed_negative": self.indexed_negative,
            "skipped": self.skipped,
            "errors": self.errors,
        }


class FeedbackIndexer:
    """Переводит размеченные feedback-ответы в RAG-индекс.

    Вызывается вручную из UI или CLI. Для каждого документа
    формирует текстовый чанк ``Q: {query}\\nA: {response}`` и
    индексирует через ``RAGService`` с metadata, включающим
    ``source=ai_feedback`` и метку оператора.

    Атрибуты:
        _repo: Репозиторий feedback-документов (через протокол).
    """

    _NAMESPACE = "ai_feedback"

    def __init__(self, repository: FeedbackRepository | None = None) -> None:
        """Создаёт индексатор.

        Args:
            repository: Репозиторий feedback. ``None`` → singleton.
        """
        self._repo = repository or get_feedback_repository()

    async def index_batch(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> FeedbackIndexResult:
        """Переводит пачку размеченных ответов в RAG-индекс.

        Берёт из репозитория размеченные документы с
        ``indexed_in_rag=False``. ``skip``-метки пропускаются.
        После успешной индексации обновляет статус документа.

        Args:
            agent_id: Фильтр по агенту; ``None`` — все.
            limit: Максимум документов за вызов (защита от перегрузки).

        Returns:
            Результат индексации (счётчики по исходу).
        """
        docs = await self._repo.list_labeled(
            agent_id=agent_id, indexed_in_rag=False, limit=limit
        )
        if not docs:
            return FeedbackIndexResult()

        rag = self._resolve_rag_service()
        result = FeedbackIndexResult()

        for doc in docs:
            if doc.feedback == "skip":
                result.skipped += 1
                continue

            try:
                rag_doc_id = await self._index_one(rag, doc)
            except Exception as exc:
                logger.error(
                    "feedback_index_error",
                    extra={"doc_id": doc.id, "error": str(exc)},
                    exc_info=True,
                )
                result.errors += 1
                continue

            doc.indexed_in_rag = True
            doc.rag_doc_id = rag_doc_id
            doc.indexed_at = _utc_now()
            await self._repo.update(doc)

            if doc.feedback == "positive":
                result.indexed_positive += 1
            elif doc.feedback == "negative":
                result.indexed_negative += 1

        logger.info("feedback_index_batch_done", extra=result.as_dict())
        return result

    async def _index_one(self, rag: object, doc: AIFeedbackDoc) -> str:
        """Индексирует один документ в RAG.

        Args:
            rag: Экземпляр ``RAGService`` (импорт lazy, избегаем cycle).
            doc: Документ с запросом, ответом и меткой.

        Returns:
            Идентификатор документа в RAG (``rag_doc_id``).
        """
        content = f"Q: {doc.query}\nA: {doc.response}"
        metadata = {
            "source": "ai_feedback",
            "label": doc.feedback,
            "agent_id": doc.agent_id,
            "original_doc_id": doc.id,
            **(doc.metadata or {}),
        }
        ingest = getattr(rag, "ingest", None)
        if ingest is None:
            raise RuntimeError("RAGService.ingest недоступен")
        rag_doc_id = await ingest(
            content=content, metadata=metadata, namespace=self._NAMESPACE
        )
        return str(rag_doc_id)

    @staticmethod
    def _resolve_rag_service() -> object:
        """Lazy-import ``RAGService`` для разрыва циклических зависимостей.

        Returns:
            Singleton ``RAGService`` из ``app.services.ai.rag_service``.
        """
        from src.services.ai.rag_service import get_rag_service

        return get_rag_service()


@app_state_singleton("ai_feedback_indexer", factory=FeedbackIndexer)
def get_feedback_indexer() -> FeedbackIndexer:
    """Возвращает singleton ``FeedbackIndexer``."""
