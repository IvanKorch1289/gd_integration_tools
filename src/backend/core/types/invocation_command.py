"""DTO для контракта :class:`ActionDispatcher` (W14.1).

Перемещены из ``src.schemas.invocation`` в ``core/types`` для устранения
зависимости ``core/interfaces`` → ``schemas`` (нарушение layer policy
после Wave 22.2-22.5). ``schemas/invocation.py`` оставлен как
переэкспорт для обратной совместимости.

Модели наследуются напрямую от ``pydantic.BaseModel`` (без
``schemas.base.BaseSchema``), чтобы core/ оставался независимым
от schemas/. Поведение (сериализация, валидация) — идентично исходной
реализации; camelCase-алиасы и ``from_attributes`` не нужны на этом
уровне (это HTTP-специфика).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.backend.core.enums.invocation import InvokeMode

__all__ = (
    "ActionCommandMetaSchema",
    "ActionCommandSchema",
    "InvocationOptionsSchema",
    "InvocationResultSchema",
)


class _CoreBaseModel(BaseModel):
    """Минимальная база для DTO в core/types.

    Без camelCase-алиасов и ``from_attributes`` — это HTTP-уровень,
    он живёт в ``schemas/``. Здесь только ``validate_assignment`` и
    ``arbitrary_types_allowed`` для совместимости с исходными моделями.
    """

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
        use_enum_values=True,
        arbitrary_types_allowed=True,
    )


class InvocationOptionsSchema(_CoreBaseModel):
    """Унифицированные параметры исполнения action.

    Attributes:
        mode: Способ выполнения действия.
        delay_seconds: Отложенный запуск в секундах.
        cron: Cron-выражение для планирования публикации.
    """

    mode: InvokeMode = Field(
        default=InvokeMode.direct, description="Режим выполнения: direct или event."
    )
    delay_seconds: int | None = Field(
        default=None, ge=1, description="Отложенный запуск в секундах."
    )
    cron: str | None = Field(
        default=None, description="Cron-выражение для планирования публикации."
    )

    @model_validator(mode="after")
    def validate_schedule(self) -> "InvocationOptionsSchema":
        """Проверяет корректность параметров расписания."""
        if self.delay_seconds is not None and self.cron is not None:
            raise ValueError("Нельзя одновременно использовать delay_seconds и cron")
        return self


class InvocationResultSchema(_CoreBaseModel):
    """Унифицированный ответ для event/scheduled вызовов."""

    status: Literal["queued", "scheduled", "completed"] = Field(
        description="Статус обработки запроса."
    )
    transport: str = Field(description="Транспорт или шина (direct, redis, rabbit).")
    job_id: str | None = Field(
        default=None, description="Идентификатор задачи (если scheduled)."
    )
    command: dict[str, Any] | None = Field(
        default=None, description="Сформированная команда для шины."
    )
    result: Any | None = Field(
        default=None, description="Результат выполнения (если direct)."
    )


class ActionCommandMetaSchema(_CoreBaseModel):
    """Служебные метаданные команды."""

    source: str = Field(default="http", description="Источник вызова команды.")
    request_path: str | None = Field(
        default=None, description="HTTP path, с которого была сформирована команда."
    )
    requested_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время формирования команды."
    )


class ActionCommandSchema(_CoreBaseModel):
    """Универсальная команда для event bus."""

    action: str = Field(description="Уникальное имя действия.")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Полезная нагрузка команды."
    )
    meta: ActionCommandMetaSchema = Field(
        default_factory=ActionCommandMetaSchema,
        description="Служебные метаданные команды.",
    )
