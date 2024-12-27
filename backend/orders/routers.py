from fastapi import APIRouter, Depends, Header, status
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
    async def get_orders(self, x_api_key: str = Header(...)):
        return await self.service.all()

    @router.get(
        "/id/{order_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить запрос по ID",
    )
    async def get_order(self, order_id: int, x_api_key: str = Header(...)):
        return await self.service.get(key="id", value=order_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить запрос по полю",
    )
    async def get_by_filter(
        self,
        order_filter: OrderFilter = FilterDepends(OrderFilter),
        x_api_key: str = Header(...),
    ):
        return await self.service.get_by_params(filter=order_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить запрос"
    )
    async def add_order(
        self, request_schema: OrderSchemaIn, x_api_key: str = Header(...)
    ):
        return await self.service.add(data=request_schema.model_dump())

    @router.post(
        "/create_skb_order_by_id/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить запрос в СКБ-Техно",
    )
    async def add_order_to_skb(self, order_id: int, x_api_key: str = Header(...)):
        return await self.service.create_skb_order(order_id=order_id)

    @router.put(
        "/update/{order_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить запроса по ID",
    )
    async def update_order(
        self, request_schema: OrderSchemaIn, order_id: int, x_api_key: str = Header(...)
    ):
        return await self.service.update(
            key="id", value=order_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{order_id}",
        status_code=status.HTTP_200_OK,
        summary="Удалить запрос по ID",
    )
    async def delete_order(self, order_id: int, x_api_key: str = Header(...)):
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
        x_api_key: str = Header(...),
        responses={
            200: {
                "description": "Successful Response",
                "content": {
                    "application/json": {},
                    "application/pdf": {},
                },
            },
        },
    ):
        return await self.service.get_order_result(
            order_id=order_id, response_type=response_type
        )

    @router.get(
        "/{order_id}/get-order-file",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    async def get_order_file(self, order_id: int, x_api_key: str = Header(...)):
        return await self.service.get_order_file_from_storage(order_id=order_id)

    @router.get(
        "/{order_id}/get-order-file-b64",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    async def get_order_file_base64(self, order_id: int, x_api_key: str = Header(...)):
        return await self.service.get_order_file_from_storage_base64(order_id=order_id)

    @router.get(
        "/{order_id}/get-order-file-link",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на файл запроса",
    )
    async def get_order_file_link(
        self,
        order_id: int,
        s3_service: S3Service = Depends(s3_bucket_service_factory),
        x_api_key: str = Header(...),
    ):
        order = await self.service.get(key="id", value=order_id)
        files_links = []
        for file in order.files:
            file_link = await s3_service.generate_download_url(str(file.object_uuid))
            files_links.append({"file": file_link})
        return {"files_links": files_links}
