"""Протокол репозитория AI-feedback (S38.4 DDD).

Определяет контракт чтения/записи ответов AI-агентов.
Все реализации (in-memory, MongoDB, Postgres) наследуют
этот протокол.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.backend.core.models.feedback import AIFeedbackDoc, FeedbackLabel

__all__ = ("FeedbackRepository",)


@runtime_checkable
class FeedbackRepository(Protocol):
    """Абстракция хранилища AI-feedback."""

    async def save(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Сохраняет документ. Возвращает сохранённую версию."""
        ...

    async def get(self, doc_id: str) -> AIFeedbackDoc | None:
        """Возвращает документ по id либо ``None``."""
        ...

    async def update(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Обновляет существующий документ.

        Raises:
            KeyError: Если документ с ``doc.id`` отсутствует.
        """
        ...

    async def list_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[AIFeedbackDoc]:
        """Возвращает ответы, ожидающие разметки."""
        ...

    async def list_labeled(
        self,
        *,
        label: FeedbackLabel | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AIFeedbackDoc]:
        """Возвращает размеченные ответы с фильтрами."""
        ...

    async def stats(self) -> dict[str, int]:
        """Агрегированная статистика.

        Returns:
            Словарь с ключами ``pending``, ``positive``, ``negative``,
            ``skip``, ``indexed``.
        """
        ...
