"""SOAP-адаптер для DSL-маршрутов.

Преобразует SOAP envelope в Exchange и отправляет
результат обратно в формате SOAP response/fault.
"""

from typing import Any

from app.dsl.adapters.base import BaseProtocolAdapter
from app.dsl.adapters.types import ProtocolType
from app.dsl.engine.exchange import Exchange, Message

__all__ = ("SoapAdapter",)


class SoapAdapter(BaseProtocolAdapter):
    """Адаптер SOAP-протокола для DSL.

    Преобразует данные SOAP-запроса (операция + payload)
    в Exchange и обратно.
    """

    protocol = ProtocolType.soap

    async def create_exchange(
        self, raw_input: Any
    ) -> Exchange[Any]:
        """Создаёт Exchange из SOAP-данных.

        Args:
            raw_input: Словарь с ключами ``operation``
                и ``payload``.

        Returns:
            Подготовленный Exchange.
        """
        operation = raw_input.get("operation", "")
        payload = raw_input.get("payload", {})
        headers = raw_input.get("headers", {})

        exchange: Exchange[Any] = Exchange(
            in_message=Message(
                body=payload,
                headers={
                    "soap-action": headers.get("soap-action", ""),
                    "soap-operation": operation,
                    **headers,
                },
            ),
        )

        self.enrich_meta(
            exchange,
            soap_operation=operation,
            soap_action=headers.get("soap-action", ""),
        )

        return exchange

    async def send_response(
        self,
        exchange: Exchange[Any],
        raw_context: Any,
    ) -> Any:
        """Возвращает результат обработки.

        Args:
            exchange: Exchange после pipeline.
            raw_context: Не используется для SOAP
                (ответ формируется в soap_handler.py).

        Returns:
            Тело выходного сообщения.
        """
        if exchange.out_message:
            return exchange.out_message.body
        return None

    async def start(self) -> None:
        """SOAP-адаптер не требует запуска (stateless)."""

    async def stop(self) -> None:
        """SOAP-адаптер не требует остановки (stateless)."""
