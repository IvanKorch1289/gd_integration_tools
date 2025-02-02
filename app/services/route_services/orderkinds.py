from typing import Type

from app.infra.db.repositories.orderkinds import get_order_kind_repo
from app.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from app.services.route_services.service_factory import (
    BaseService,
    create_service_class,
)


__all__ = ("get_order_kind_service",)


def get_order_kind_service() -> Type[BaseService]:
    """
    Возвращает экземпляр сервиса для работы с видами заказов.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр OrderKindService.
    """
    return create_service_class(
        repo=get_order_kind_repo(),
        response_schema=OrderKindSchemaOut,
        request_schema=OrderKindSchemaIn,
        version_schema=OrderKindVersionSchemaOut,
    )
