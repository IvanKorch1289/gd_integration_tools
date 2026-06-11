"""Domain service AI Feedback (S38.4 DDD).

Содержит чистую бизнес-логику разметки ответов AI-агентов,
независимую от хранилища и UI.

Правила (invariants):
* Разметить можно только существующий документ.
* Переразметка разрешена (оператор может исправить ошибку),
  но старая метка и время сохраняются в истории
  (в текущей версии — перезапись с обновлением ``labeled_at``).
* ``skip`` — допустимая метка, означает "не применимо".
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.backend.core.models.feedback import AIFeedbackDoc, FeedbackLabel

__all__ = ("FeedbackDomainService",)


def _utc_now() -> datetime:
    """Возвращает текущий момент в UTC (aware)."""
    return datetime.now(UTC)


class FeedbackDomainService:
    """Доменный сервис обратной связи.

    Не взаимодействует с хранилищем — только принимает
    загруженные агрегаты и применяет к ним бизнес-правила.
    """

    @staticmethod
    def apply_label(
        doc: AIFeedbackDoc,
        *,
        label: FeedbackLabel,
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> AIFeedbackDoc:
        """Применяет метку оператора к документу.

        Args:
            doc: Существующий документ (должен быть загружен из хранилища).
            label: Новая метка.
            comment: Комментарий оператора.
            operator_id: Идентификатор оператора (для аудита).

        Returns:
            Тот же экземпляр с обновлёнными полями.

        Raises:
            ValueError: При попытке разметить ``None``-документ.
        """
        if doc is None:  # pragma: no cover — defensive
            raise ValueError("Cannot label a None document")

        doc.feedback = label
        doc.feedback_comment = comment
        doc.operator_id = operator_id
        doc.labeled_at = _utc_now()
        return doc

    @staticmethod
    def mark_indexed(doc: AIFeedbackDoc, rag_doc_id: str) -> AIFeedbackDoc:
        """Помечает документ как проиндексированный в RAG.

        Args:
            doc: Документ для обновления.
            rag_doc_id: Идентификатор документа в RAG.

        Returns:
            Обновлённый документ.
        """
        doc.indexed_in_rag = True
        doc.rag_doc_id = rag_doc_id
        doc.indexed_at = _utc_now()
        return doc
