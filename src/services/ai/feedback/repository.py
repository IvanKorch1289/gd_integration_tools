"""Репозиторий AI Feedback — абстракция над хранилищем.

Определяет протокол ``FeedbackRepository`` для записи, чтения
и обновления ответов AI-агентов. В Wave 4 реализация — in-memory
(``InMemoryFeedbackRepository``); в Wave 9 подключается MongoDB.

Singleton-accessor ``get_feedback_repository()`` использует
``app_state_singleton``, что позволяет внедрять конкретную
реализацию через FastAPI lifespan (подмена на Mongo/Postgres
без изменения сервисов).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from src.infrastructure.application.di import app_state_singleton
from src.services.ai.feedback.models import AIFeedbackDoc, FeedbackLabel

__all__ = (
    "FeedbackRepository",
    "InMemoryFeedbackRepository",
    "get_feedback_repository",
)


def _utc_now() -> datetime:
    """Возвращает текущий момент в UTC (aware).

    Returns:
        Текущее UTC-время.
    """
    return datetime.now(timezone.utc)


@runtime_checkable
class FeedbackRepository(Protocol):
    """Протокол хранилища AI-feedback.

    Определяет контракт, независимый от конкретного бэкенда
    (in-memory, MongoDB, Postgres). Сервисы ``AIFeedbackService``
    и ``FeedbackIndexer`` работают только через этот протокол.
    """

    async def save(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Сохраняет документ. Возвращает сохранённую версию.

        Args:
            doc: Документ ответа AI-агента.

        Returns:
            Документ, фактически записанный в хранилище.
        """
        ...

    async def get(self, doc_id: str) -> AIFeedbackDoc | None:
        """Возвращает документ по идентификатору.

        Args:
            doc_id: Уникальный идентификатор документа.

        Returns:
            Документ либо ``None``, если не найден.
        """
        ...

    async def update(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Обновляет существующий документ целиком.

        Args:
            doc: Документ с актуальными полями.

        Returns:
            Обновлённый документ.

        Raises:
            KeyError: Если документ с ``doc.id`` отсутствует.
        """
        ...

    async def list_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[AIFeedbackDoc]:
        """Возвращает ответы, ожидающие разметки (``feedback is None``).

        Args:
            agent_id: Фильтр по агенту; ``None`` — все.
            limit: Размер страницы.
            offset: Смещение.

        Returns:
            Отсортированный по ``created_at`` DESC список.
        """
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
        """Возвращает размеченные ответы с фильтрами.

        Args:
            label: Фильтр по метке; ``None`` — все размеченные.
            agent_id: Фильтр по агенту.
            indexed_in_rag: Фильтр по статусу индексации в RAG.
            limit: Размер страницы.
            offset: Смещение.

        Returns:
            Отсортированный по ``labeled_at`` DESC список.
        """
        ...

    async def stats(self) -> dict[str, int]:
        """Статистика документов в хранилище.

        Returns:
            Словарь с ключами: ``pending``, ``positive``, ``negative``,
            ``skip``, ``indexed``.
        """
        ...


class InMemoryFeedbackRepository:
    """In-memory реализация ``FeedbackRepository``.

    Используется в Wave 4 как переходный вариант. Хранит
    документы в словаре под asyncio-lock для потокобезопасности
    в рамках одного процесса. Не подходит для multi-instance
    deployment — в Wave 9 будет заменён MongoDB.

    Атрибуты:
        _docs: Словарь ``{id: AIFeedbackDoc}``.
        _lock: ``asyncio.Lock`` для изоляции конкурентных записей.
    """

    def __init__(self) -> None:
        """Создаёт пустое in-memory хранилище."""
        self._docs: dict[str, AIFeedbackDoc] = {}
        self._lock = asyncio.Lock()

    async def save(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Сохраняет новый документ.

        Args:
            doc: Документ ответа AI-агента.

        Returns:
            Сохранённая копия документа.
        """
        async with self._lock:
            self._docs[doc.id] = doc.model_copy(deep=True)
            return self._docs[doc.id]

    async def get(self, doc_id: str) -> AIFeedbackDoc | None:
        """Возвращает документ по id или ``None``.

        Args:
            doc_id: Идентификатор документа.

        Returns:
            Копия документа либо ``None``.
        """
        async with self._lock:
            doc = self._docs.get(doc_id)
            return doc.model_copy(deep=True) if doc else None

    async def update(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        """Обновляет документ.

        Args:
            doc: Документ с актуальными полями.

        Returns:
            Обновлённая копия документа.

        Raises:
            KeyError: Если документ с ``doc.id`` отсутствует.
        """
        async with self._lock:
            if doc.id not in self._docs:
                raise KeyError(f"AIFeedbackDoc {doc.id!r} не найден")
            self._docs[doc.id] = doc.model_copy(deep=True)
            return self._docs[doc.id]

    async def list_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[AIFeedbackDoc]:
        """Возвращает pending-документы с фильтром по агенту."""
        async with self._lock:
            docs = [
                d
                for d in self._docs.values()
                if d.feedback is None and (agent_id is None or d.agent_id == agent_id)
            ]
        docs.sort(key=lambda d: d.created_at, reverse=True)
        return [d.model_copy(deep=True) for d in docs[offset : offset + limit]]

    async def list_labeled(
        self,
        *,
        label: FeedbackLabel | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AIFeedbackDoc]:
        """Возвращает размеченные документы с комбинированным фильтром."""
        async with self._lock:
            docs = [
                d
                for d in self._docs.values()
                if d.feedback is not None
                and (label is None or d.feedback == label)
                and (agent_id is None or d.agent_id == agent_id)
                and (indexed_in_rag is None or d.indexed_in_rag == indexed_in_rag)
            ]
        docs.sort(key=lambda d: d.labeled_at or _utc_now(), reverse=True)
        return [d.model_copy(deep=True) for d in docs[offset : offset + limit]]

    async def stats(self) -> dict[str, int]:
        """Возвращает агрегированную статистику документов."""
        async with self._lock:
            docs = list(self._docs.values())
        result = {"pending": 0, "positive": 0, "negative": 0, "skip": 0, "indexed": 0}
        for doc in docs:
            if doc.feedback is None:
                result["pending"] += 1
            else:
                result[doc.feedback] += 1
                if doc.indexed_in_rag:
                    result["indexed"] += 1
        return result

    async def ensure_indexes(self) -> None:
        """In-memory не требует индексов; метод нужен для совместимости с Mongo."""
        return None


def _default_repository_factory() -> FeedbackRepository:
    """Mongo-репозиторий с fallback на in-memory.

    Wave 9.2: drop-in замена ``InMemoryFeedbackRepository``. Если Mongo-
    инфраструктура недоступна — fallback на in-memory сохраняется.
    """
    try:
        from src.infrastructure.repositories.ai_feedback_mongo import (
            MongoFeedbackRepository,
        )

        return MongoFeedbackRepository()
    except Exception:  # noqa: BLE001
        return InMemoryFeedbackRepository()


@app_state_singleton("ai_feedback_repository", factory=_default_repository_factory)
def get_feedback_repository() -> FeedbackRepository:
    """Возвращает singleton ``FeedbackRepository``.

    По умолчанию — ``MongoFeedbackRepository`` (Wave 9.2);
    fallback — ``InMemoryFeedbackRepository``.
    """
