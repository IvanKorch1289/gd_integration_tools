from typing import Any

from fastapi import HTTPException, Request

from src.core.config.runtime_state import disabled_feature_flags
from src.core.config.settings import settings
from src.core.svcs_registry import list_services as _list_services
from src.dsl.commands.action_registry import action_handler_registry
from src.dsl.commands.registry import route_registry
from src.infrastructure.clients.storage.redis import redis_client

__all__ = ("AdminService", "get_admin_service")


class AdminService:
    """
    Сервис для административных action-роутов.

    Выносит из transport-слоя:
    - получение конфигурации приложения;
    - переключение доступности endpoint-ов;
    - операции с Redis-кэшем.

    Благодаря этому admin-роуты остаются тонкими и пригодными
    для декларативного описания через ActionSpec.
    """

    async def get_config(self) -> dict[str, Any]:
        """
        Возвращает текущую конфигурацию приложения.

        Returns:
            dict[str, Any]: Конфигурация приложения в виде словаря.
        """
        return settings.model_dump()

    async def toggle_route(
        self, request: Request, route_path: str, enable: bool
    ) -> dict[str, str]:
        """
        Активирует или деактивирует указанный маршрут.

        Args:
            request: Текущий FastAPI Request.
            route_path: Путь маршрута, который требуется переключить.
            enable: Флаг включения/выключения маршрута.

        Returns:
            dict[str, str]: Результат выполнения операции.

        Raises:
            HTTPException: Если маршрут с указанным путём не найден.
        """
        from src.core.config.runtime_state import blocked_routes

        route_exists = any(route.path == route_path for route in request.app.routes)
        if not route_exists:
            raise HTTPException(status_code=404, detail="Route not found")

        if enable:
            blocked_routes.discard(route_path)
        else:
            blocked_routes.add(route_path)

        return {"status": "success"}

    async def list_cache_keys(self, pattern: str = "*") -> Any:
        """
        Возвращает список ключей Redis по шаблону.

        Args:
            pattern: Redis pattern для поиска ключей.

        Returns:
            Any: Список ключей или совместимый с ним тип ответа.
        """
        return await redis_client.list_cache_keys(pattern)

    async def get_cache_value(self, key: str) -> Any:
        """
        Возвращает значение по ключу Redis.

        Args:
            key: Ключ Redis.

        Returns:
            Any: Значение, сохранённое по ключу.
        """
        return await redis_client.get_cache_value(key)

    async def invalidate_cache(self) -> Any:
        """
        Полностью инвалидирует Redis-кэш.

        Returns:
            Any: Результат операции очистки кэша.
        """
        return await redis_client.invalidate_cache()

    # ------------------------------------------------------------------
    #  Информационные методы (introspection)
    # ------------------------------------------------------------------

    async def list_services(self) -> dict[str, Any]:
        """Возвращает список зарегистрированных сервисов."""
        return {"services": _list_services()}

    async def list_actions(self) -> dict[str, Any]:
        """Возвращает список зарегистрированных action-команд."""
        return {"actions": list(action_handler_registry.list_actions())}

    async def list_routes(self) -> dict[str, Any]:
        """Возвращает все DSL-маршруты с их статусом."""
        all_routes = route_registry.list_routes()
        enabled = set(route_registry.list_enabled_routes())
        flags = route_registry.get_route_feature_flags()
        return {
            "total": len(all_routes),
            "routes": [
                {"route_id": r, "enabled": r in enabled, "feature_flag": flags.get(r)}
                for r in all_routes
            ],
        }

    async def list_feature_flags(self) -> dict[str, Any]:
        """Возвращает состояние всех feature-флагов."""
        flags = route_registry.get_route_feature_flags()
        unique_flags = sorted(set(flags.values()))
        return {
            "flags": [
                {
                    "name": f,
                    "enabled": f not in disabled_feature_flags,
                    "routes": [r for r, fl in flags.items() if fl == f],
                }
                for f in unique_flags
            ]
        }

    async def toggle_feature_flag(self, flag_name: str, enable: bool) -> dict[str, Any]:
        """Включает/отключает feature-флаг.

        Args:
            flag_name: Имя feature-флага.
            enable: True — включить, False — отключить.

        Returns:
            dict с результатом операции.
        """
        route_registry.toggle_feature_flag(flag_name, enable=enable)
        affected = [
            r
            for r, fl in route_registry.get_route_feature_flags().items()
            if fl == flag_name
        ]
        return {"flag": flag_name, "enabled": enable, "affected_routes": affected}

    async def system_info(self) -> dict[str, Any]:
        """Сводная информация о системе."""
        return {
            "services": _list_services(),
            "actions_count": len(action_handler_registry.list_actions()),
            "routes_total": len(route_registry.list_routes()),
            "routes_enabled": len(route_registry.list_enabled_routes()),
            "routes_disabled": len(route_registry.list_disabled_routes()),
            "feature_flags_disabled": sorted(disabled_feature_flags),
        }

    async def slo_report(self) -> dict[str, Any]:
        """SLO-отчёт: P50/P95/P99 per route."""
        from src.infrastructure.application.slo_tracker import get_slo_tracker

        return get_slo_tracker().get_report()


_admin_service_instance = AdminService()


def get_admin_service() -> AdminService:
    """
    Фабрика административного сервиса.

    Returns:
        AdminRouteService: Экземпляр сервиса admin-роутов.
    """
    return _admin_service_instance
