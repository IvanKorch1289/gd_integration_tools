from typing import List

from fastapi import APIRouter, Header, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.order_kinds.filters import OrderKindFilter
from backend.order_kinds.schemas import OrderKindSchemaIn
from backend.order_kinds.service import OrderKindService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    service = OrderKindService()

    @router.get(
        "/all/", status_code=status.HTTP_200_OK, summary="Получить все виды запросов"
    )
    async def get_kinds(self, x_api_key: str = Header(...)):
        return await self.service.all()

    @router.get(
        "/id/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по ID",
    )
    async def get_kind(self, kind_id: int, x_api_key: str = Header(...)):
        return await self.service.get(key="id", value=kind_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить вид запроса по полю",
    )
    async def get_by_filter(
        self,
        order_kind_filter: OrderKindFilter = FilterDepends(OrderKindFilter),
        x_api_key: str = Header(...),
    ):
        return await self.service.get_by_params(filter=order_kind_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить вид запроса"
    )
    async def add_kind(
        self, request_schema: OrderKindSchemaIn, x_api_key: str = Header(...)
    ):
        return await self.service.add(data=request_schema.model_dump())

    @router.post(
        "/create_many/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить несколько видов запроса",
    )
    async def add_many_kinds(
        self, request_schema: List[OrderKindSchemaIn], x_api_key: str = Header(...)
    ):
        data_list = [schema.model_dump() for schema in request_schema]
        return await self.service.add_many(data_list=data_list)

    @router.put(
        "/update/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить вид запроса по ID",
    )
    async def update_kind(
        self,
        request_schema: OrderKindSchemaIn,
        kind_id: int,
        x_api_key: str = Header(...),
    ):
        return await self.service.update(
            key="id", value=kind_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{kind_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить вид запроса по ID",
    )
    async def delete_kind(self, kind_id: int, x_api_key: str = Header(...)):
        return await self.service.delete(key="id", value=kind_id)
