from pydantic import BaseModel

from app.repositories.orderkinds import (
    OrderKindRepository,
    get_order_kind_repo,
)
from app.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from app.services.route_services.base import BaseService


__all__ = ("get_order_kind_service",)


class OrderKindService(BaseService[OrderKindRepository]):
    """
    Сервис для работы с видами заказами. Обеспечивает создание, обновление, получение и обработку видов заказов
    """

    def __init__(
        self,
        schema_in: BaseModel,
        schema_out: BaseModel,
        version_schema: BaseModel,
        repo: OrderKindRepository,
    ):
        """
        Инициализация сервиса видов заказов.

        :param response_schema: Схема для преобразования данных в ответ.
        :param request_schema: Схема для валидации входных данных.
        :param version_schema: Схема для валидации выходных данных версии.
        :param repo: Репозиторий для работы с видами заказов.
        """
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )


def get_order_kind_service() -> OrderKindService:
    """
    Возвращает экземпляр сервиса для работы с видами заказов.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр OrderKindService.
    """
    return OrderKindService(
        repo=get_order_kind_repo(),
        schema_in=OrderKindSchemaIn,
        schema_out=OrderKindSchemaOut,
        version_schema=OrderKindVersionSchemaOut,
    )
