from fastapi import APIRouter, Depends

from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import ActionRouterBuilder, CrudSpec
from src.backend.schemas.filter_schemas.users import UserFilter
from src.backend.schemas.route_schemas.users import (
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)
from src.backend.services.core.users import get_user_service
from src.backend.services.decorators.limiting import route_limiting

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)

common_dependencies = [Depends(require_api_key)]
common_decorators = [route_limiting]
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
        decorators=common_decorators,
        tags=common_tags,
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)
