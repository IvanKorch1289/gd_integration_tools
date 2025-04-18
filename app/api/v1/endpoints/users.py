from fastapi import APIRouter

from app.api.routers_factory import create_router_class
from app.schemas.filter_schemas.users import UserFilter
from app.schemas.route_schemas.users import UserSchemaIn
from app.services.route_services.users import get_user_service


__all__ = ("router",)


router = APIRouter()


UserCBV = create_router_class(
    router=router,
    schema_in=UserSchemaIn,
    service=get_user_service(),
    filter_class=UserFilter,
)
