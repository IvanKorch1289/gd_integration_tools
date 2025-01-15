from backend.base.service import BaseService
from backend.order_kinds.repository import OrderKindRepository
from backend.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindService",)


class OrderKindService(BaseService):
    """
    Сервис для работы с видами запросов.

    Наследует функциональность базового сервиса (BaseService) и использует
    репозиторий OrderKindRepository для взаимодействия с данными видов запросов.

    Атрибуты:
        repo (OrderKindRepository): Репозиторий для работы с видами запросов.
        response_schema (OrderKindSchemaOut): Схема для преобразования данных в ответ.
    """

    repo = OrderKindRepository()
    response_schema = OrderKindSchemaOut
