"""HTTP-схемы для REST-эндпоинтов :class:`Invoker` (W22.2).

Чёткое отделение от :mod:`src.schemas.invocation` (старые схемы для
ActionDispatcher event-bus) — здесь только публичный contract REST API
``/api/v1/invocations``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from src.backend.schemas.base import BaseSchema

__all__ = ("InvocationRequestSchema", "InvocationResponseSchema")

#: Допустимые режимы вызова (string-aliases :class:`InvocationMode`).
InvocationModeLiteral = Literal[
    "sync", "async-api", "async-queue", "deferred", "background", "streaming"
]


class InvocationRequestSchema(BaseSchema):
    """Тело POST /api/v1/invocations.

    ``mode`` контролирует поведение:

    * ``sync`` — блокирующий вызов; в ответе ``result`` либо ``error``.
    * ``async-api`` — fire-and-forget; результат в polling-канале (GET /{id}).
    * ``background`` — fire-and-forget без сохранения результата.
    * ``streaming`` — push в WS-канал по invocation_id (см. ``/ws/invocations``).
    * ``async-queue`` / ``deferred`` — пока возвращают ERROR (W22+ TaskIQ/APS).
    """

    action: str = Field(
        description="Зарегистрированный action в ActionDispatcher (e.g. 'orders.add').",
        min_length=1,
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Полезная нагрузка вызова."
    )
    mode: InvocationModeLiteral = Field(
        default="sync", description="Режим выполнения через Invoker."
    )
    reply_channel: str | None = Field(
        default=None,
        description=(
            "Тип канала ответа (api/ws/queue/email/express). "
            "По умолчанию подбирается режимом."
        ),
    )


class InvocationResponseSchema(BaseSchema):
    """Унифицированный JSON-ответ Invoker."""

    invocation_id: str = Field(
        description="Уникальный id вызова — единый для трейсинга."
    )
    status: Literal["ok", "accepted", "error"] = Field(
        description="Финальный статус (sync/streaming) либо подтверждение приёма."
    )
    mode: InvocationModeLiteral = Field(
        description="Режим, с которым был запущен вызов."
    )
    result: Any | None = Field(
        default=None, description="Результат (только для sync; иначе null)."
    )
    error: str | None = Field(
        default=None, description="Текст ошибки (если status=error)."
    )
