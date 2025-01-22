from fastapi import Depends
from pydantic import BaseModel

from backend.base.service import BaseService
from backend.orderkinds.repository import (
    OrderKindRepository,
    get_order_kind_repo,
)
from backend.orderkinds.schemas import OrderKindSchemaIn, OrderKindSchemaOut


__all__ = (
    "OrderKindService",
    "get_order_kind_service",
)


class OrderKindService(BaseService):
    """
    Сервис для работы с видами запросов.

    Наследует функциональность базового сервиса (BaseService) и использует
    репозиторий OrderKindRepository для взаимодействия с данными видов запросов.

    Атрибуты:
        repo (OrderKindRepository): Репозиторий для работы с видами запросов.
        response_schema (OrderKindSchemaOut): Схема для преобразования данных в ответ.
        request_schema (OrderKindSchemaIn): Схема для валидации входных данных.
    """

    def __init__(
        self,
        response_schema: BaseModel,
        request_schema: BaseModel,
        repo: OrderKindRepository = Depends(get_order_kind_repo),
    ):
        """
        Инициализация сервиса для работы с видами запросов.

        :param repo: Репозиторий для работы с видами запросов.
        :param response_schema: Схема для преобразования данных в ответ.
        :param request_schema: Схема для валидации входных данных.
        """
        super().__init__(
            repo=repo, response_schema=response_schema, request_schema=request_schema
        )


def get_order_kind_service() -> OrderKindService:
    """
    Возвращает экземпляр сервиса для работы с видами заказов.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр OrderKindService.
    """
    return OrderKindService(
        repo=get_order_kind_repo(),
        response_schema=OrderKindSchemaOut,
        request_schema=OrderKindSchemaIn,
    )
