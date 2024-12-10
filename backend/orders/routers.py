from fastapi import APIRouter, Depends, Request, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.api_skb.enums import ResponseTypeChoices
from backend.core.dependencies import (
    create_zip_streaming_response,
    get_base64_file,
    get_streaming_response,
)
from backend.core.storage import S3Service, s3_bucket_service_factory
from backend.orders.filters import OrderFilter
from backend.orders.schemas import OrderSchemaIn
from backend.orders.service import OrderService


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
        status_code=status.HTTP_200_OK,
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
        "/{order_id}/get-order-file",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    async def get_order_file(
        self,
        request: Request,
        order_id: int,
        service: S3Service = Depends(s3_bucket_service_factory),
    ):
        order = await self.service.get(key="id", value=order_id)
        files_list = []
        for file in order.files:
            file_uuid = str(file.object_uuid)
            files_list.append(file_uuid)

        if len(files_list) == 1:
            file_uuid = files_list[0]
            return await get_streaming_response(file_uuid, service)
        elif len(files_list) > 1:
            return await create_zip_streaming_response(files_list, service)

    @router.get(
        "/{order_id}/get-order-file-b64",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    async def get_order_file_base64(
        self, order_id: int, service: S3Service = Depends(s3_bucket_service_factory)
    ):
        order = await self.service.get(key="id", value=order_id)
        files_list = []
        for file in order.files:
            base64_file = await get_base64_file(str(file.object_uuid), service)
            files_list.append({"file": base64_file})
        return {"files": files_list}
