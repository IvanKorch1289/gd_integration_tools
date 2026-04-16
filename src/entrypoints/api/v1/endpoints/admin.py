from fastapi import APIRouter

from app.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from app.schemas.route_schemas.admin import (
    AdminCacheKeysQuerySchema,
    AdminCacheValuePathSchema,
    AdminToggleRouteQuerySchema,
)
from app.services.admin import get_admin_service

__all__ = ("router",)


router = APIRouter()


ActionRouterBuilder(router).add_actions(
    [
        ActionSpec(
            name="get_config",
            method="GET",
            path="/config",
            summary="Получить текущую конфигурацию",
            description="Возвращает текущую конфигурацию приложения.",
            service_getter=get_admin_service,
            service_method="get_config",
        ),
        ActionSpec(
            name="toggle_route",
            method="POST",
            path="/routes/toggle",
            summary="Активировать/деактивировать эндпоинты",
            description=(
                "Активирует или деактивирует указанный endpoint по его route path."
            ),
            service_getter=get_admin_service,
            service_method="toggle_route",
            query_model=AdminToggleRouteQuerySchema,
            request_argument_name="request",
        ),
        ActionSpec(
            name="list_cache_keys",
            method="GET",
            path="/cache/keys",
            summary="Получить список ключей кэша по шаблону",
            description="Возвращает список ключей кэша по Redis pattern.",
            service_getter=get_admin_service,
            service_method="list_cache_keys",
            query_model=AdminCacheKeysQuerySchema,
        ),
        ActionSpec(
            name="get_cache_value",
            method="GET",
            path="/cache/{key}",
            summary="Получить значение по ключу кэша",
            description="Возвращает значение по указанному ключу кэша.",
            service_getter=get_admin_service,
            service_method="get_cache_value",
            path_model=AdminCacheValuePathSchema,
        ),
        ActionSpec(
            name="invalidate_cache",
            method="DELETE",
            path="/cache/invalidate",
            summary="Инвалидировать кэш",
            description="Инвалидирует весь Redis-кэш.",
            service_getter=get_admin_service,
            service_method="invalidate_cache",
        ),
    ]
)
