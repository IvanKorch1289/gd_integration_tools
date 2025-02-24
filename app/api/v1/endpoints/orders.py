from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import FileResponse
from fastapi_utils.cbv import cbv

from app.api.routers_factory import create_router_class
from app.schemas.filter_schemas.orders import OrderFilter
from app.schemas.route_schemas.orders import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from app.services.infra_services.s3 import S3Service, get_s3_service_dependency
from app.services.route_services.orders import get_order_service
from app.utils.decorators.limiting import route_limiting
from app.utils.errors import handle_routes_errors


__all__ = ("router",)


router = APIRouter()


OrderCBV = create_router_class(
    router=router,
    schema_in=OrderSchemaIn,
    schema_out=OrderSchemaOut,
    version_schema=OrderVersionSchemaOut,
    service=get_order_service(),
    filter_class=OrderFilter,
)


@cbv(router)
class ExtendedOrderCBV(OrderCBV):  # type: ignore
    """CBV-класс для работы с запросами."""

    @router.post(
        "/create_skb_order_by_id/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить запрос в СКБ-Техно",
    )
    @handle_routes_errors
    async def add_order_to_skb(
        self, request: Request, order_id: int, x_api_key: str = Header(...)
    ):
        """
        Добавить запрос в СКБ-Техно.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат добавления запроса.
        """
        return await self.service.create_skb_order(order_id=order_id)

    @router.post(
        "/async-create-skb-order-by-id/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить запрос в СКБ-Техно фоновой задачей",
    )
    @handle_routes_errors
    async def async_add_order_to_skb(
        self, request: Request, order_id: int, x_api_key: str = Header(...)
    ):
        """
        Добавить запрос в СКБ-Техно.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат добавления запроса.
        """
        return await self.service.async_create_skb_order(order_id=order_id)

    @router.get(
        "/{order_id}/get-result",
        status_code=status.HTTP_200_OK,
        summary="Получить результат запроса",
    )
    @route_limiting
    @handle_routes_errors
    async def get_order_result_from_skb(
        self, request: Request, order_id: int, x_api_key: str = Header(...)
    ):
        """
        Получить результат запроса из СКБ-Техно.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат запроса.
        """
        return await self.service.get_order_file_and_json_from_skb(
            order_id=order_id
        )

    @router.get(
        "/{order_id}/async-get-result",
        status_code=status.HTTP_200_OK,
        summary="Получить результат запроса фоновой задачей",
    )
    @route_limiting
    @handle_routes_errors
    async def async_get_order_result_from_skb(
        self, request: Request, order_id: int, x_api_key: str = Header(...)
    ):
        """
        Получить результат запроса из СКБ-Техно.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат запроса.
        """
        return await self.service.async_get_order_file_and_json_from_skb(
            order_id=order_id
        )

    @router.get(
        "/{order_id}/get-order-file",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    @route_limiting
    @handle_routes_errors
    async def get_order_file(
        self,
        request: Request,
        order_id: int,
        x_api_key: str = Header(...),
        s3_service: S3Service = Depends(get_s3_service_dependency),
    ) -> FileResponse:
        """
        Получить файл запроса из хранилища.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :param s3_service: Сервис для работы с S3.
        :return: Файл запроса.
        """
        return await self.service.get_order_file_from_storage(
            order_id=order_id, s3_service=s3_service
        )

    @router.get(
        "/{order_id}/get-order-file-b64",
        status_code=status.HTTP_200_OK,
        summary="Получить файл запроса",
    )
    @route_limiting
    @handle_routes_errors
    async def get_order_file_base64(
        self,
        request: Request,
        order_id: int,
        x_api_key: str = Header(...),
        s3_service: S3Service = Depends(get_s3_service_dependency),
    ):
        """
        Получить файл запроса в формате Base64.

        :param order_id: ID запроса.
        :param x_api_key: API-ключ для аутентификации.
        :param s3_service: Сервис для работы с S3.
        :return: Файл запроса в формате Base64.
        """
        return await self.service.get_order_file_from_storage_base64(
            order_id=order_id, s3_service=s3_service
        )

    @router.get(
        "/{order_id}/get-order-file-link",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на файл запроса",
    )
    @route_limiting
    @handle_routes_errors
    async def get_order_file_link(
        self,
        request: Request,
        order_id: int,
        s3_service: S3Service = Depends(get_s3_service_dependency),
        x_api_key: str = Header(...),
    ):
        """
        Получить ссылку на файл запроса.

        :param order_id: ID запроса.
        :param s3_service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Ссылка на файл запроса.
        """
        return await self.service.get_order_file_from_storage_link(
            order_id=order_id, s3_service=s3_service
        )

    @router.get(
        "/{order_id}/get-order-json-and-file-link",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на файл запроса",
    )
    @route_limiting
    @handle_routes_errors
    async def get_order_file_link_and_json_result_for_request(
        self,
        request: Request,
        order_id: int,
        s3_service: S3Service = Depends(get_s3_service_dependency),
        x_api_key: str = Header(...),
    ):
        """
        Получить ссылку на файл запроса и JSON-результат.

        :param order_id: ID запроса.
        :param s3_service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Ссылка на файл и JSON-результат.
        """
        return (
            await self.service.get_order_file_link_and_json_result_for_request(
                order_id=order_id, s3_service=s3_service
            )
        )
