from fastapi import APIRouter

from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.infrastructure.cache.metrics_collector import get_cache_metrics_snapshot
from src.backend.schemas.route_schemas.admin import (
    AdminCacheInvalidatePatternSchema,
    AdminCacheInvalidateTagsSchema,
    AdminCacheInvalidateTableSchema,
    AdminCacheKeysQuerySchema,
    AdminCacheValuePathSchema,
    AdminToggleFeatureFlagQuerySchema,
    AdminToggleRouteQuerySchema,
)
from src.backend.services.core.admin import get_admin_service

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
        ActionSpec(
            name="invalidate_cache_by_pattern",
            method="DELETE",
            path="/cache/invalidate/pattern",
            summary="Инвалидировать кэш по паттерну",
            description="Инвалидирует все ключи, matching glob pattern.",
            service_getter=get_admin_service,
            service_method="invalidate_cache_by_pattern",
            query_model=AdminCacheInvalidatePatternSchema,
        ),
        ActionSpec(
            name="invalidate_cache_by_tag",
            method="DELETE",
            path="/cache/invalidate/tags",
            summary="Инвалидировать кэш по тегам",
            description="Инвалидирует все ключи с указанными тегами.",
            service_getter=get_admin_service,
            service_method="invalidate_cache_by_tag",
            query_model=AdminCacheInvalidateTagsSchema,
        ),
        ActionSpec(
            name="invalidate_table",
            method="DELETE",
            path="/cache/invalidate/table",
            summary="Инвалидировать кэш по имени таблицы",
            description="Инвалидирует все ключи с тегом table:<table>.",
            service_getter=get_admin_service,
            service_method="invalidate_table",
            query_model=AdminCacheInvalidateTableSchema,
        ),
        # -- Introspection endpoints --
        ActionSpec(
            name="list_services",
            method="GET",
            path="/services",
            summary="Список зарегистрированных сервисов",
            description="Возвращает имена всех сервисов из svcs registry.",
            service_getter=get_admin_service,
            service_method="list_services",
        ),
        ActionSpec(
            name="list_actions",
            method="GET",
            path="/actions",
            summary="Список зарегистрированных action-команд",
            description="Возвращает имена всех actions из ActionHandlerRegistry.",
            service_getter=get_admin_service,
            service_method="list_actions",
        ),
        ActionSpec(
            name="list_routes",
            method="GET",
            path="/routes",
            summary="Список DSL-маршрутов",
            description="Возвращает все маршруты с их статусом и feature-флагами.",
            service_getter=get_admin_service,
            service_method="list_routes",
        ),
        ActionSpec(
            name="list_feature_flags",
            method="GET",
            path="/feature-flags",
            summary="Список feature-флагов",
            description="Возвращает все feature-флаги и связанные маршруты.",
            service_getter=get_admin_service,
            service_method="list_feature_flags",
        ),
        ActionSpec(
            name="toggle_feature_flag",
            method="POST",
            path="/feature-flags/toggle",
            summary="Включить/отключить feature-флаг",
            description="Переключает feature-флаг. Отключённый флаг блокирует связанные DSL-маршруты.",
            service_getter=get_admin_service,
            service_method="toggle_feature_flag",
            query_model=AdminToggleFeatureFlagQuerySchema,
        ),
        ActionSpec(
            name="system_info",
            method="GET",
            path="/system-info",
            summary="Сводная информация о системе",
            description="Возвращает количество сервисов, actions, маршрутов и feature-флагов.",
            service_getter=get_admin_service,
            service_method="system_info",
        ),
        ActionSpec(
            name="slo_report",
            method="GET",
            path="/slo-report",
            summary="SLO-отчёт по маршрутам",
            description="P50/P95/P99 latency, error rate per route.",
            service_getter=get_admin_service,
            service_method="slo_report",
        ),
    ]
)


async def _reload_config() -> dict[str, object]:
    """Эндпоинт ручного триггера hot-reload.

    Возвращает агрегированный отчёт из :class:`ConfigHotReloader`.
    """
    from src.backend.core.config.hot_reload import get_hot_reloader

    return await get_hot_reloader().trigger_reload(reason="api-request")


router.add_api_route(
    path="/config/reload",
    endpoint=_reload_config,
    methods=["POST"],
    summary="Горячая перезагрузка конфигурации",
    description=(
        "Вручную запускает все зарегистрированные config-reload колбеки "
        "(без рестарта процесса). Используйте когда FS watcher недоступен."
    ),
    name="reload_config",
)


async def _get_cache_stats() -> dict[str, object]:
    """Эндпоинт получения снимка метрик кэша.

    Возвращает агрегированные метрики из всех tier'ов кэша.
    """
    return get_cache_metrics_snapshot()


router.add_api_route(
    path="/cache/stats",
    endpoint=_get_cache_stats,
    methods=["GET"],
    summary="Метрики кэша",
    description=(
        "Возвращает снимок метрик кэша: hit/miss для LRU, RAG и semantic tier."
    ),
    name="get_cache_stats",
)
