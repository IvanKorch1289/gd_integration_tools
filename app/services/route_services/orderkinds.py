import asyncio
from typing import Any, Dict

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
from app.services.route_services.skb import APISKBService, get_skb_service
from app.utils.decorators.caching import response_cache
from app.utils.decorators.singleton import singleton


__all__ = ("get_order_kind_service",)


@singleton
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
        request_service: APISKBService,
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
        self.request_service = request_service

    @response_cache
    async def create_or_update_kinds_from_skb(self) -> Dict[str, Any]:
        """
        Создает или обновляет виды заказов на основе данных из СКБ-Техно.

        Метод выполняет следующие действия:
        1. Запрашивает данные из СКБ-Техно через `request_service`.
        2. Обрабатывает полученные данные и сохраняет их в репозитории `OrderKindService`.
        3. Для каждого элемента данных:
        - Ищет или создает запись в репозитории по полю `skb_uuid`.
        - Обновляет или создает запись с данными `name` и `skb_uuid`.
        4. Возвращает результат запроса к СКБ-Техно.

        :return: Результат запроса к СКБ-Техно в виде модели `BaseModel` или `None`, если произошла ошибка.
        :raises Exception: Если произошла ошибка при выполнении запроса или обработке данных.
        """
        try:
            result = await self.request_service.get_request_kinds()

            # Обработка и сохранение данных в OrderKindService
            tasks = [
                self.get_or_add(
                    key="skb_uuid",
                    value=el.get("Id"),
                    data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                )
                for el in result.get("data", []).get("Data", None)
            ]
            await asyncio.gather(*tasks)

            return result
        except Exception:
            raise


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
        request_service=get_skb_service(),
    )
