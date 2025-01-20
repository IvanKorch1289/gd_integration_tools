from typing import List

from fastapi import APIRouter, Header, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.limiter import route_limiter
from backend.orderkinds.filters import OrderKindFilter
from backend.orderkinds.schemas import OrderKindSchemaIn
from backend.orderkinds.service import OrderKindService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """
    CBV-класс для работы со справочником видов запросов.

    Предоставляет методы для получения, добавления, обновления и удаления видов запросов.
    """

    service = OrderKindService()

    @router.get(
        "/all/", status_code=status.HTTP_200_OK, summary="Получить все виды запросов"
    )
    @route_limiter
    async def get_kinds(self, request: Request, x_api_key: str = Header(...)):
        """
        Получить все виды запросов из базы данных.

        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех видов запросов.
        """
        return await self.service.all()

    @router.get(
        "/id/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по ID",
    )
    async def get_kind(self, kind_id: int, x_api_key: str = Header(...)):
        """
        Получить вид запроса по его ID.

        :param kind_id: ID вида запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Вид запроса с указанным ID.
        """
        return await self.service.get(key="id", value=kind_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по фильтру",
    )
    async def get_by_filter(
        self,
        order_kind_filter: OrderKindFilter = FilterDepends(OrderKindFilter),
        x_api_key: str = Header(...),
    ):
        """
        Получить виды запросов, соответствующие указанному фильтру.

        :param order_kind_filter: Фильтр для поиска видов запросов.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список видов запросов, соответствующих фильтру.
        """
        return await self.service.get_by_params(filter=order_kind_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить вид запроса"
    )
    @route_limiter
    async def add_kind(
        self,
        request_schema: OrderKindSchemaIn,
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Добавить новый вид запроса в базу данных.

        :param request_schema: Данные для создания вида запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Созданный вид запроса.
        """
        return await self.service.add(data=request_schema.model_dump())

    @router.post(
        "/create_many/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить несколько видов запроса",
    )
    async def add_many_kinds(
        self,
        request_schema: List[OrderKindSchemaIn],
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Добавить несколько видов запросов в базу данных.

        :param request_schema: Список данных для создания видов запросов.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список созданных видов запросов.
        """
        data_list = [schema.model_dump() for schema in request_schema]
        return await self.service.add_many(data_list=data_list)

    @router.put(
        "/update/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
    )
    @route_limiter
    async def update_kind(
        self,
        request_schema: OrderKindSchemaIn,
        kind_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Обновить вид запроса по его ID.

        :param request_schema: Данные для обновления вида запроса.
        :param kind_id: ID вида запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Обновленный вид запроса.
        """
        return await self.service.update(
            key="id", value=kind_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{kind_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить вид запроса по ID",
    )
    @route_limiter
    async def delete_kind(
        self, kind_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Удалить вид запроса по его ID.

        :param kind_id: ID вида запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Сообщение об успешном удалении.
        """
        return await self.service.delete(key="id", value=kind_id)
