from fastapi import APIRouter, Depends

from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import ActionRouterBuilder, CrudSpec
from src.backend.entrypoints.middlewares.rate_limit import get_default_rate_limiter
from src.backend.schemas.filter_schemas.users import UserFilter
from src.backend.schemas.route_schemas.users import (
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)
from src.backend.services.core.users import get_user_service

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)

common_dependencies = [Depends(require_api_key), Depends(get_default_rate_limiter())]
common_tags = ("Users",)


builder.add_crud_resource(
    CrudSpec(
        name="users",
        service_getter=get_user_service,
        schema_in=UserSchemaIn,
        schema_out=UserSchemaOut,
        version_schema=UserVersionSchemaOut,
        filter_class=UserFilter,
        dependencies=common_dependencies,
        tags=common_tags,
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)
