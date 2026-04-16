import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

__all__ = ("ExchangeStatus", "Message", "ExchangeMeta", "Exchange")

T = TypeVar("T")


class ExchangeStatus(str, Enum):
    """
    Статус выполнения Exchange внутри DSL-маршрута.
    """

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Message(BaseModel, Generic[T]):
    """
    Универсальное сообщение DSL.

    Attributes:
        headers: Транспортно-агностичные заголовки.
        body: Полезная нагрузка.
    """

    headers: dict[str, Any] = Field(default_factory=dict)
    body: T | None = None

    def get_header(self, key: str, default: Any = None) -> Any:
        """
        Возвращает заголовок по ключу.

        Args:
            key: Имя заголовка.
            default: Значение по умолчанию.

        Returns:
            Any: Значение заголовка или default.
        """
        return self.headers.get(key, default)

    def set_header(self, key: str, value: Any) -> None:
        """
        Устанавливает заголовок.

        Args:
            key: Имя заголовка.
            value: Значение заголовка.
        """
        self.headers[key] = value


class ExchangeMeta(BaseModel):
    """
    Служебные метаданные Exchange.

    Attributes:
        exchange_id: Уникальный идентификатор конкретного обмена.
        route_id: Идентификатор маршрута.
        correlation_id: Идентификатор цепочки вызовов.
        created_at: Время создания Exchange.
        source: Имя входного источника (http, grpc, redis, rabbit и т.д.).
    """

    exchange_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    route_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str | None = None


class Exchange(BaseModel, Generic[T]):
    """
    Контейнер, который движется по DSL-маршруту.

    Аналог Camel Exchange:
    - `in_message` — входные данные;
    - `out_message` — результат обработки;
    - `properties` — внутренний runtime-контекст маршрута;
    - `meta` — служебные метаданные;
    - `status/error` — текущее состояние выполнения.
    """

    meta: ExchangeMeta = Field(default_factory=ExchangeMeta)
    in_message: Message[T] = Field(default_factory=Message)
    out_message: Message[Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    status: ExchangeStatus = ExchangeStatus.pending
    error: str | None = None

    def get_property(self, key: str, default: Any = None) -> Any:
        """
        Возвращает runtime-свойство маршрута.

        Args:
            key: Ключ свойства.
            default: Значение по умолчанию.

        Returns:
            Any: Значение свойства или default.
        """
        return self.properties.get(key, default)

    def set_property(self, key: str, value: Any) -> None:
        """
        Устанавливает runtime-свойство маршрута.

        Args:
            key: Ключ свойства.
            value: Значение свойства.
        """
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        """
        Устанавливает выходное сообщение.

        Args:
            body: Результирующее тело.
            headers: Результирующие заголовки.
        """
        self.out_message = Message(body=body, headers=headers or {})

    def complete(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        """
        Завершает Exchange успешно.

        Args:
            body: Результирующее тело.
            headers: Результирующие заголовки.
        """
        self.set_out(body=body, headers=headers)
        self.status = ExchangeStatus.completed
        self.error = None

    def fail(self, reason: str) -> None:
        """
        Завершает Exchange ошибкой.

        Args:
            reason: Текст ошибки.
        """
        self.status = ExchangeStatus.failed
        self.error = reason
