from fastapi import APIRouter

from app.api.routers_factory import create_router_class
from app.schemas import (
    UserFilter,
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)
from app.services import get_user_service


__all__ = ("router",)


router = APIRouter()


UserCBV = create_router_class(
    router=router,
    schema_in=UserSchemaIn,
    schema_out=UserSchemaOut,
    version_schema_out=UserVersionSchemaOut,
    service=get_user_service(),
    filter_class=UserFilter,
)
