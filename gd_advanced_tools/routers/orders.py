import httpx
from fastapi import APIRouter, Request, UploadFile, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from gd_advanced_tools.enums import ResponseTypeChoices
from gd_advanced_tools.filters import OrderFilter
from gd_advanced_tools.schemas import OrderSchemaIn
from gd_advanced_tools.services import OrderService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class OrderCBV:
    """CBV-класс для работы с запросами."""

    service = OrderService()

    @router.get("/all/", status_code=status.HTTP_200_OK, summary="Получить все запросы")
    async def get_orders(self):
        return await self.service.all()

    @router.get(
        "/id/{order_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить запрос по ID",
    )
    async def get_order(self, order_id: int):
        return await self.service.get(key="id", value=order_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить запрос по полю",
    )
    async def get_by_filter(
        self, order_filter: OrderFilter = FilterDepends(OrderFilter)
    ):
        return await self.service.get_by_params(filter=order_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить запрос"
    )
    async def add_order(self, request_schema: OrderSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{order_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить запроса по ID",
    )
    async def update_order(self, request_schema: OrderSchemaIn, order_id: int):
        return await self.service.update(
            key="id", value=order_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{order_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить запрос по ID",
    )
    async def delete_order(self, order_id: int):
        return await self.service.delete(key="id", value=order_id)

    @router.get(
        "/{order_id}/get-result",
        status_code=status.HTTP_200_OK,
        summary="Получить результат запроса",
    )
    async def get_order_result(
        self,
        order_id: int,
        response_type: ResponseTypeChoices = ResponseTypeChoices.json,
    ):
        return await self.service.get_order_result(
            order_id=order_id, response_type=response_type
        )

    @router.get(
        "/{order_id}/get-file",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    async def another_route(self, request: Request, order_id: int):
        order = await self.service.get(key="id", value=order_id)
        for file in order.files:
            url = f"{request.base_url}download_file/{str(file.object_uuid)}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url=url)
                return response.url
            return response.json()
