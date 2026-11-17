"""Users CRUD endpoints — auto-generated via ``make_crud_router``.

Routes registered:
* ``GET /api/v1/users`` — список (фильтрация через ``UserFilter``);
* ``GET /api/v1/users/{object_id}`` — детальная карточка;
* ``POST /api/v1/users`` — создание (``UserSchemaIn``);
* ``PUT /api/v1/users/{object_id}`` — обновление;
* ``DELETE /api/v1/users/{object_id}`` — удаление.

Auth: ``X-API-Key`` (см. ``common_dependencies``).
"""

from fastapi import APIRouter, Depends

from src.backend.core.extension_registry import get_extension_resource
from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import ActionRouterBuilder, CrudSpec
from src.backend.entrypoints.dependencies.rate_limit import get_default_rate_limiter

__all__ = ("router",)


# ADR-0457: объекты расширения получаются через core-реестр (инверсия
# зависимости ``src/ → extensions``), а не прямым импортом ``extensions.*``.
# Резолв на уровне модуля — FastAPI строит модель при импорте.
UserFilter = get_extension_resource("users", "schema", "filter")
UserSchemaIn = get_extension_resource("users", "schema", "schema_in")
UserSchemaOut = get_extension_resource("users", "schema", "schema_out")
UserVersionSchemaOut = get_extension_resource("users", "schema", "version_schema")
get_user_service = get_extension_resource("users", "service", "users")


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
