from uuid import UUID, uuid4

from pydantic import Field

from app.schemas import BaseSchema


__all__ = ("ApiOrderSchemaIn",)


class ApiOrderSchemaIn(BaseSchema):
    """
    Схема для входящих данных запроса в СКБ-Техно.

    Атрибуты:
        Id (UUID): Уникальный идентификатор запроса. По умолчанию генерируется случайный UUID.
        OrderId (UUID): Уникальный идентификатор заказа. По умолчанию генерируется случайный UUID.
        Number (str): Номер запроса.
        Priority (int): Приоритет запроса. По умолчанию 80.
        RequestType (str): Тип запроса.
    """

    Id: UUID = Field(default=uuid4())
    OrderId: UUID = Field(default=uuid4())
    Number: str
    Priority: int = 80
    RequestType: str
