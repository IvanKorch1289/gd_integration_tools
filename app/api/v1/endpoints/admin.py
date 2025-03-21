from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi_utils.cbv import cbv

from app.config.settings import settings
from app.infra.clients.redis import redis_client


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class AdminCBV:
    """
    CBV-класс для управления приложением.

    Предоставляет эндпоинты для получения конфигурации, проверки состояния
    сервисов и отправки тестовых email.
    """

    @router.get(
        "/config",
        summary="Получить текущую конфигурацию",
        operation_id="get_config",
    )
    async def get_config(self) -> Dict[str, Any]:
        """
        Возвращает текущую конфигурацию приложения.

        Returns:
            Dict[str, Any]: Конфигурация приложения.
        """
        return settings.model_dump()

    @router.post(
        "/routes/toggle",
        summary="Активировать/деактивировать эндпоинты",
        operation_id="toggle_route",
    )
    async def toggle_route(
        self, request: Request, route_path: str, enable: bool
    ) -> Dict[str, str]:
        """
        Активирует/деактивирует указанный эндпоинт.

        Returns:
            Dict[str, str]: Результат.
        """
        from app.utils.middlewares.blocked_routes import blocked_routes

        app = request.app

        # Ищем маршрут по пути
        route_to_toggle = None

        for route in app.routes:
            if route.path == route_path:
                route_to_toggle = route
                break

        if not route_to_toggle:
            raise HTTPException(status_code=404, detail="Route not found")

        if enable:
            blocked_routes.discard(route_path)
        else:
            blocked_routes.add(route_path)
        return {"status": "success"}

    @router.get(
        "/cache/keys",
        summary="Получить список ключей кэша по шаблону",
        operation_id="list_cache_keys",
    )
    async def list_cache_keys(self, pattern: str = "*"):
        """Возвращает список ключей кэша, соответствующих шаблону."""
        return await redis_client.list_cache_keys(pattern)

    @router.get(
        "/cache/{key}",
        summary="Получить значение по ключу кэша",
        operation_id="get_cache_value",
    )
    async def get_cache_value(self, key: str):
        """Возвращает значение по ключу кэша."""
        return await redis_client.get_cache_value(key)

    @router.delete(
        "/cache/invalidate",
        summary="Инвалидировать кэш",
        operation_id="invalidate_cache",
    )
    async def invalidate_cache(self):
        """Инвалидирует весь кэш (удаляет все ключи)."""
        return await redis_client.invalidate_cache()
