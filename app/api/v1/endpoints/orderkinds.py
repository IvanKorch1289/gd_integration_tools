from fastapi import APIRouter, Header, Request, status
from fastapi_utils.cbv import cbv

from app.api.routers_factory import create_router_class
from app.schemas.filter_schemas.orderkinds import OrderKindFilter
from app.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from app.services.route_services.orderkinds import get_order_kind_service
from app.utils.errors import handle_routes_errors


__all__ = ("router",)


router = APIRouter()


OrderKindCBV = create_router_class(
    router=router,
    schema_in=OrderKindSchemaIn,
    schema_out=OrderKindSchemaOut,
    version_schema=OrderKindVersionSchemaOut,
    service=get_order_kind_service(),
    filter_class=OrderKindFilter,
)


@cbv(router)
class ExtendedOrderKindCBV(OrderKindCBV):  # type: ignore
    """CBV-класс для работы с видами запросов."""

    @router.get(
        "/create_or_update_from_skb/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить/Обновить виды запросов из СКБ-Техно",
    )
    @handle_routes_errors
    async def create_or_update_kinfs_from_skb(
        self, request: Request, x_api_key: str = Header(...)
    ):
        """
        Добавить запрос в СКБ-Техно.

        :return: Результат добавления/обновления запросов.
        """
        return await self.service.create_or_update_kinds_from_skb()
