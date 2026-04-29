"""AIFeedbackService — бизнес-логика разметки ответов AI-агентов.

Сервис инкапсулирует работу с ``FeedbackRepository``:
  * автоматическое сохранение ответа (вызывается из ``AIAgentService``);
  * разметка ответа оператором (``positive`` / ``negative`` / ``skip``);
  * выдача списков pending/labeled для UI и CLI;
  * агрегированная статистика.

Сервис не знает деталей хранилища — работает только через
протокол ``FeedbackRepository``, что позволяет менять бэкенд
без изменения вызывающего кода.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.core.di import app_state_singleton
from src.services.ai.feedback.models import AIFeedbackDoc, FeedbackLabel
from src.services.ai.feedback.repository import (
    FeedbackRepository,
    get_feedback_repository,
)

__all__ = ("AIFeedbackService", "get_ai_feedback_service")

logger = logging.getLogger("services.ai.feedback")


def _utc_now() -> datetime:
    """Возвращает текущий момент в UTC (aware)."""
    return datetime.now(timezone.utc)


class AIFeedbackService:
    """Сервис управления обратной связью по ответам AI-агентов.

    Отвечает за:
      * сохранение каждого ответа в момент его генерации агентом;
      * разметку ответов оператором с комментарием;
      * выдачу списков ожидающих/размеченных ответов;
      * агрегированную статистику по меткам и индексации.

    Атрибуты:
        _repo: Репозиторий feedback-документов (через протокол).
    """

    def __init__(self, repository: FeedbackRepository | None = None) -> None:
        """Создаёт сервис.

        Args:
            repository: Репозиторий feedback. ``None`` → singleton
                из ``get_feedback_repository()``.
        """
        self._repo = repository or get_feedback_repository()

    async def save_response(
        self,
        *,
        query: str,
        response: str,
        agent_id: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Сохраняет ответ агента для последующей разметки.

        Вызывается автоматически из ``AIAgentService.chat/run_agent``
        после успешного ответа. Поле ``feedback`` остаётся ``None``
        до ручной разметки оператором.

        Args:
            query: Исходный запрос пользователя.
            response: Текст ответа агента.
            agent_id: Идентификатор агента.
            session_id: Идентификатор сессии, если есть.
            metadata: Дополнительные поля (tenant_id, провайдер и т.д.).

        Returns:
            Идентификатор сохранённого документа.
        """
        doc = AIFeedbackDoc(
            query=query,
            response=response,
            agent_id=agent_id,
            session_id=session_id,
            metadata=metadata or {},
        )
        saved = await self._repo.save(doc)
        logger.info(
            "ai_feedback_saved", extra={"doc_id": saved.id, "agent_id": agent_id}
        )
        return saved.id

    async def set_feedback(
        self,
        *,
        doc_id: str,
        label: FeedbackLabel,
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> AIFeedbackDoc:
        """Проставляет метку обратной связи оператором.

        Args:
            doc_id: Идентификатор документа.
            label: ``positive`` / ``negative`` / ``skip``.
            comment: Комментарий оператора.
            operator_id: Идентификатор оператора (для аудита).

        Returns:
            Обновлённый документ.

        Raises:
            KeyError: Документ не найден.
        """
        existing = await self._repo.get(doc_id)
        if existing is None:
            raise KeyError(f"AIFeedbackDoc {doc_id!r} не найден")

        existing.feedback = label
        existing.feedback_comment = comment
        existing.operator_id = operator_id
        existing.labeled_at = _utc_now()
        updated = await self._repo.update(existing)

        self._record_metric(agent_id=updated.agent_id, label=label)
        logger.info(
            "ai_feedback_labeled",
            extra={"doc_id": doc_id, "label": label, "operator_id": operator_id},
        )
        return updated

    @staticmethod
    def _record_metric(*, agent_id: str, label: FeedbackLabel) -> None:
        """Отправляет в Prometheus счётчик разметки.

        Ошибки записи метрики не пробрасываются наверх: метрики
        не должны ломать бизнес-поток.

        Args:
            agent_id: Идентификатор агента.
            label: Проставленная метка.
        """
        try:
            from src.services.ai.metrics import get_agent_metrics_service

            get_agent_metrics_service().record_feedback(agent_id=agent_id, label=label)
        except Exception as exc:
            logger.debug("ai_feedback_metric_skipped: %s", exc)

    async def list_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[AIFeedbackDoc]:
        """Возвращает ответы, ожидающие разметки.

        Args:
            agent_id: Фильтр по агенту.
            limit: Размер страницы (макс. 200).
            offset: Смещение пагинации.

        Returns:
            Список документов (свежие первыми).
        """
        return await self._repo.list_pending(
            agent_id=agent_id, limit=min(limit, 200), offset=max(offset, 0)
        )

    async def list_labeled(
        self,
        *,
        label: FeedbackLabel | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AIFeedbackDoc]:
        """Возвращает размеченные ответы.

        Args:
            label: Фильтр по метке; ``None`` — все размеченные.
            agent_id: Фильтр по агенту.
            indexed_in_rag: Фильтр по статусу индексации.
            limit: Размер страницы.
            offset: Смещение.

        Returns:
            Список документов (свежие по ``labeled_at`` первыми).
        """
        return await self._repo.list_labeled(
            label=label,
            agent_id=agent_id,
            indexed_in_rag=indexed_in_rag,
            limit=min(limit, 500),
            offset=max(offset, 0),
        )

    async def get(self, doc_id: str) -> AIFeedbackDoc | None:
        """Возвращает документ по id или ``None``.

        Args:
            doc_id: Идентификатор документа.

        Returns:
            Документ либо ``None``.
        """
        return await self._repo.get(doc_id)

    async def stats(self) -> dict[str, int]:
        """Агрегированная статистика документов.

        Returns:
            Словарь ``{pending, positive, negative, skip, indexed}``.
        """
        return await self._repo.stats()


@app_state_singleton("ai_feedback_service", factory=AIFeedbackService)
def get_ai_feedback_service() -> AIFeedbackService:
    """Возвращает singleton ``AIFeedbackService``.

    Источник экземпляра — ``app.state.ai_feedback_service`` (подмена
    через lifespan) либо lazy-init через фабрику.
    """
