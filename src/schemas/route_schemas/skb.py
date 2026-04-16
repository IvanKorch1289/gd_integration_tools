from uuid import UUID, uuid4

from pydantic import Field

from app.core.enums.skb import ResponseTypeChoices
from app.schemas.base import BaseSchema

__all__ = (
    "APISKBOrderSchemaIn",
    "SKBResultQuerySchema",
    "SKBOrdersListQuerySchema",
    "SKBObjectsByAddressQuerySchema",
)


class APISKBOrderSchemaIn(BaseSchema):
    """
    Схема входящего тела запроса для создания запроса в СКБ-Техно.

    Используется endpoint-ом создания нового запроса в СКБ.
    Поля `Id` и `OrderId` генерируются автоматически, если клиент их не передал.

    Attributes:
        Id: Уникальный идентификатор запроса.
        OrderId: Уникальный идентификатор заказа.
        Number: Номер запроса.
        Priority: Приоритет запроса.
        RequestType: Тип запроса.
    """

    Id: UUID = Field(
        default_factory=uuid4, description="Уникальный идентификатор запроса."
    )
    OrderId: UUID = Field(
        default_factory=uuid4, description="Уникальный идентификатор заказа."
    )
    Number: str = Field(description="Номер запроса.")
    Priority: int = Field(default=80, description="Приоритет запроса.")
    RequestType: str = Field(description="Тип запроса.")


class SKBResultQuerySchema(BaseSchema):
    """
    Схема query-параметров для получения результата запроса из СКБ-Техно.

    Attributes:
        order_uuid: UUID ранее созданного запроса.
        response_type: Формат ответа - JSON или PDF.
    """

    order_uuid: UUID = Field(description="UUID ранее созданного запроса.")
    response_type: ResponseTypeChoices = Field(
        default=ResponseTypeChoices.json, description="Формат ответа: JSON или PDF."
    )


class SKBOrdersListQuerySchema(BaseSchema):
    """
    Схема query-параметров для получения списка заказов из СКБ-Техно.

    Attributes:
        take: Количество записей для выборки.
        skip: Количество записей, которые нужно пропустить.
    """

    take: int | None = Field(
        default=None, ge=1, description="Количество записей для выборки."
    )
    skip: int | None = Field(
        default=None, ge=0, description="Количество записей, которые нужно пропустить."
    )


class SKBObjectsByAddressQuerySchema(BaseSchema):
    """
    Схема query-параметров для поиска объектов недвижимости по адресу.

    Endpoint сохраняет текущий внешний контракт:
    это POST-запрос, но параметры передаются через query string.

    Attributes:
        query: Адрес объекта.
        comment: Дополнительный комментарий.
    """

    query: str = Field(description="Адрес объекта.")
    comment: str | None = Field(default=None, description="Дополнительный комментарий.")
