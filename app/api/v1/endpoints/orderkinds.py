from fastapi import APIRouter

from app.api.routers_factory import create_router_class
from app.schemas.filter_schemas.orderkinds import OrderKindFilter
from app.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from app.services.route_services.orderkinds import get_order_kind_service


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
