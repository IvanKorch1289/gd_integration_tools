"""FeedbackProcessor — DSL step ``.record_feedback()`` (S10 K4 W2).

Записывает feedback по результату выполнения route/workflow в
:class:`~src.backend.services.ai.feedback.feedback_service.AIFeedbackService`.
Поддерживает 3 точки данных:

* ``rating`` — числовая оценка (1-5) или текстовая метка
  (``positive``/``negative``/``neutral``);
* ``comment`` — свободный текст (опц.);
* ``route_run_id`` — ID конкретного запуска (используется как ``session_id``).

Использование в YAML::

    - record_feedback:
        rating_from: body.rating
        comment_from: body.comment
        route_run_id_from: exchange.correlation_id

Builder::

    .record_feedback(
        rating=Ref("body.rating"),
        comment=Ref("body.comment"),
        route_run_id=Ref("correlation_id"),
    )
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.entity import _resolve

__all__ = ("FeedbackProcessor",)

_logger = get_logger("dsl.feedback")

_VALID_LABELS = frozenset({"positive", "negative", "neutral", "skip"})


class FeedbackProcessor(BaseProcessor):
    """Записывает feedback в AIFeedbackService.

    Args:
        rating: явная оценка (число 1-5 или label из _VALID_LABELS).
        rating_from: выражение для извлечения rating из exchange.
        comment: статический комментарий.
        comment_from: выражение для извлечения comment.
        route_run_id: явный route_run_id (используется как session_id).
        route_run_id_from: выражение для извлечения route_run_id.
        agent_id: ID агента (default "route_feedback").
        result_property: куда положить id сохранённого feedback-doc.
    """

    def __init__(
        self,
        *,
        rating: str | int | None = None,
        rating_from: str | None = None,
        comment: str | None = None,
        comment_from: str | None = None,
        route_run_id: str | None = None,
        route_run_id_from: str | None = None,
        agent_id: str = "route_feedback",
        result_property: str = "feedback_doc_id",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры step."""
        super().__init__(name=name or "record_feedback")
        if rating is None and rating_from is None:
            raise ValueError("FeedbackProcessor: укажите rating или rating_from")
        self._rating = rating
        self._rating_from = rating_from
        self._comment = comment
        self._comment_from = comment_from
        self._route_run_id = route_run_id
        self._route_run_id_from = route_run_id_from
        self._agent_id = agent_id
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Сохраняет ответ + label в FeedbackService."""
        rating: Any = (
            _resolve(exchange, self._rating_from)
            if self._rating_from is not None
            else self._rating
        )
        if rating is None:
            exchange.fail("FeedbackProcessor: пустой rating")
            return

        comment = (
            _resolve(exchange, self._comment_from)
            if self._comment_from is not None
            else self._comment
        )

        route_run_id = (
            str(_resolve(exchange, self._route_run_id_from))
            if self._route_run_id_from is not None
            else self._route_run_id
        )

        try:
            service = self._build_service()
            body_str = self._stringify(exchange)
            doc_id = await service.save_response(
                query=str(rating),
                response=body_str,
                agent_id=self._agent_id,
                session_id=route_run_id,
                metadata={
                    "rating": rating,
                    "comment": comment,
                    "route_run_id": route_run_id,
                },
            )
            # Если rating — known label, сразу применим feedback.
            if isinstance(rating, str) and rating.lower() in _VALID_LABELS:
                await service.set_feedback(
                    doc_id=doc_id, label=rating.lower(), comment=comment
                )
            exchange.set_property(self._result_property, doc_id)
            _logger.info(
                "feedback.recorded",
                extra={
                    "doc_id": doc_id,
                    "rating": rating,
                    "route_run_id": route_run_id,
                },
            )
        except Exception as exc:
            _logger.warning("FeedbackProcessor: ошибка записи: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    @staticmethod
    def _stringify(exchange: Exchange[Any]) -> str:
        """Сериализует body для записи в response-поле."""
        body = exchange.in_message.body
        if isinstance(body, (bytes, bytearray)):
            try:
                return body.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                return repr(body)
        return "" if body is None else str(body)

    @staticmethod
    def _build_service() -> Any:
        """Лениво получает AIFeedbackService через DI."""
        from src.backend.services.ai.feedback.feedback_service import (
            get_ai_feedback_service,
        )

        return get_ai_feedback_service()

    def to_spec(self) -> dict:
        """YAML round-trip."""
        spec: dict[str, Any] = {
            "agent_id": self._agent_id,
            "result_property": self._result_property,
        }
        if self._rating is not None:
            spec["rating"] = self._rating
        if self._rating_from is not None:
            spec["rating_from"] = self._rating_from
        if self._comment is not None:
            spec["comment"] = self._comment
        if self._comment_from is not None:
            spec["comment_from"] = self._comment_from
        if self._route_run_id is not None:
            spec["route_run_id"] = self._route_run_id
        if self._route_run_id_from is not None:
            spec["route_run_id_from"] = self._route_run_id_from
        return {"record_feedback": spec}
