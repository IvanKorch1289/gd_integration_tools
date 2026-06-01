"""Базовый класс протокольного адаптера.

Каждый протокол (REST, SOAP, gRPC, WebSocket и др.) реализует
``BaseProtocolAdapter``, который отвечает за:

- Преобразование входящих данных протокола в ``Exchange``.
- Отправку результата обработки обратно через протокол.
- Управление жизненным циклом (start/stop).
"""

from abc import ABC, abstractmethod
from typing import Any

from src.backend.dsl.adapters.types import ProtocolType
from src.backend.dsl.engine.exchange import Exchange

__all__ = ("BaseProtocolAdapter",)


class BaseProtocolAdapter(ABC):
    """Абстрактный базовый класс для протокольных адаптеров.

    Адаптер — мост между конкретным транспортом (HTTP, gRPC,
    Kafka и т.д.) и протоколо-агностичным ядром DSL (Exchange,
    Pipeline, ExecutionEngine).

    Attrs:
        protocol: Тип протокола, обслуживаемого адаптером.
    """

    protocol: ProtocolType

    @abstractmethod
    async def create_exchange(self, raw_input: Any) -> Exchange[Any]:
        """Преобразует входящие данные протокола в Exchange.

        Args:
            raw_input: Сырые данные протокола (HTTP Request,
                protobuf message, Kafka ConsumerRecord и т.д.).

        Returns:
            Подготовленный ``Exchange`` для обработки pipeline.
        """

    @abstractmethod
    async def send_response(self, exchange: Exchange[Any], raw_context: Any) -> Any:
        """Отправляет результат обработки обратно через протокол.

        Args:
            exchange: Exchange после выполнения pipeline.
            raw_context: Контекст протокола (HTTP Response,
                gRPC context, WebSocket connection и т.д.).

        Returns:
            Результат в формате протокола.
        """

    @abstractmethod
    async def start(self) -> None:
        """Запускает адаптер (подписка, listen, polling и т.д.)."""

    @abstractmethod
    async def stop(self) -> None:
        """Останавливает адаптер и освобождает ресурсы."""

    def enrich_meta(self, exchange: Exchange[Any], **kwargs: Any) -> None:
        """Обогащает ExchangeMeta протокол-специфичными данными.

        Args:
            exchange: Exchange для обогащения.
            **kwargs: Протокол-специфичные атрибуты
                (например, ``soap_action``, ``grpc_status``).
        """
        exchange.meta.protocol = self.protocol
        exchange.meta.protocol_attrs.update(kwargs)
