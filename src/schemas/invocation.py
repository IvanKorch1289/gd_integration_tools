from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.core.enums.invocation import InvokeMode
from app.schemas.base import BaseSchema

__all__ = (
    "InvocationOptionsSchema",
    "InvocationResultSchema",
    "ActionCommandMetaSchema",
    "ActionCommandSchema",
)


class InvocationOptionsSchema(BaseSchema):
    """
    Унифицированные параметры исполнения action.

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
        """
        Проверяет корректность параметров расписания.
        """
        if self.delay_seconds is not None and self.cron is not None:
            raise ValueError("Нельзя одновременно использовать delay_seconds и cron")
        return self


class InvocationResultSchema(BaseSchema):
    """
    Унифицированный ответ для event/scheduled вызовов.
    """

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


class ActionCommandMetaSchema(BaseSchema):
    """
    Служебные метаданные команды.
    """

    source: str = Field(default="http", description="Источник вызова команды.")
    request_path: str | None = Field(
        default=None, description="HTTP path, с которого была сформирована команда."
    )
    requested_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время формирования команды."
    )


class ActionCommandSchema(BaseSchema):
    """
    Универсальная команда для event bus.
    """

    action: str = Field(description="Уникальное имя действия.")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Полезная нагрузка команды."
    )
    meta: ActionCommandMetaSchema = Field(
        default_factory=ActionCommandMetaSchema,
        description="Служебные метаданные команды.",
    )
