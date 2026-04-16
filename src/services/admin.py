from typing import Any

from fastapi import HTTPException, Request

from app.core.config.settings import settings
from app.infrastructure.clients.redis import redis_client

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
        from app.core.config.runtime_state import blocked_routes

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


def get_admin_service() -> AdminService:
    """
    Фабрика административного сервиса.

    Returns:
        AdminRouteService: Экземпляр сервиса admin-роутов.
    """
    return AdminService()
