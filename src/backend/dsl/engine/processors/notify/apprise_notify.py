"""DSL-процессор ``notify_apprise`` — multi-channel уведомления через Apprise.

Регистрируется в ProcessorRegistry как ``notify_apprise`` (namespace ``notification``).
Делегирует отправку в :class:`~src.backend.services.notifications.AppriseNotificationService`.

Пример YAML-шага::

    steps:
      - notify_apprise:
          channel: slack
          title: "Заявка обработана"
          body: "Заявка #${body.id} принята в обработку."
          body_format: text
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("AppriseNotifyProcessor",)

_log = logging.getLogger(__name__)


class AppriseNotifyParams(BaseModel):
    """Параметры шага ``notify_apprise`` в YAML DSL.

    Attributes:
        channel: Имя зарегистрированного канала (e.g. ``"slack"``).
        title: Заголовок уведомления.
        body: Тело уведомления.
        body_format: Формат тела — ``text`` | ``html`` | ``markdown``.
        result_property: Куда записать результат (``True``/``False``).
    """

    channel: str = Field(..., description="Имя канала Apprise (зарегистрированного)")
    title: str = Field(..., description="Заголовок уведомления")
    body: str = Field(..., description="Тело уведомления")
    body_format: str = Field(
        default="text", description="Формат тела: text|html|markdown"
    )
    result_property: str = Field(
        default="notify_apprise_result", description="Имя property для результата"
    )


class AppriseNotifyProcessor(BaseProcessor):
    """Процессор DSL-шага ``notify_apprise`` (S3 K3 W1).

    Обёртка над :class:`~src.backend.services.notifications.AppriseNotificationService`.
    Поддерживает single-channel через :attr:`channel`. Для multi-channel
    используйте несколько шагов или обратитесь к сервису напрямую через
    :meth:`~AppriseNotificationService.notify_multi`.

    Зарегистрирован в ProcessorRegistry как ``notify_apprise``
    (namespace ``notification``).

    Args:
        channel: Имя зарегистрированного канала.
        title: Заголовок уведомления.
        body: Тело уведомления (шаблон-строка или статичный текст).
        body_format: Формат тела (``text`` | ``html`` | ``markdown``).
        result_property: Имя exchange-property для результата доставки.
        name: Имя процессора для логов/observability.
    """

    def __init__(
        self,
        channel: str,
        title: str,
        body: str,
        *,
        body_format: str = "text",
        result_property: str = "notify_apprise_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"notify_apprise:{channel}")
        self.channel = channel
        self.title = title
        self.body = body
        self.body_format = body_format
        self.result_property = result_property

    @classmethod
    def from_params(cls, params: AppriseNotifyParams) -> "AppriseNotifyProcessor":
        """Фабричный метод из Pydantic-модели параметров.

        Args:
            params: Параметры шага из YAML DSL.

        Returns:
            Сконфигурированный экземпляр :class:`AppriseNotifyProcessor`.
        """
        return cls(
            channel=params.channel,
            title=params.title,
            body=params.body,
            body_format=params.body_format,
            result_property=params.result_property,
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет отправку уведомления через AppriseNotificationService.

        При успехе пишет ``True`` в ``result_property``.
        При неудаче — ``False``, exchange НЕ останавливается (fire-and-forget семантика).
        """
        from src.backend.services.notifications.apprise_service import (
            get_notification_service,
        )

        svc = get_notification_service()
        result = await svc.notify(
            channel=self.channel,
            title=self.title,
            body=self.body,
            body_format=self.body_format,
        )
        exchange.set_property(self.result_property, result)
        if not result:
            _log.warning(
                "AppriseNotifyProcessor: уведомление в '%s' не доставлено.",
                self.channel,
            )

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML DSL."""
        return {
            "notify_apprise": {
                "channel": self.channel,
                "title": self.title,
                "body": self.body,
                "body_format": self.body_format,
                "result_property": self.result_property,
            }
        }
