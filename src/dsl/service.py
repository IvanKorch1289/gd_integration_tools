from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.execution_engine import ExecutionEngine
from app.dsl.registry import route_registry

__all__ = ("DslService", "get_dsl_service")


class DslService:
    """
    Facade над RouteRegistry + ExecutionEngine.

    Нужен для entrypoints, чтобы они не работали
    напрямую с low-level объектами DSL.
    """

    def __init__(self, engine: ExecutionEngine | None = None) -> None:
        self._engine = engine or ExecutionEngine()

    async def dispatch(
        self,
        route_id: str,
        *,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> Exchange[Any]:
        """
        Выполняет зарегистрированный DSL-маршрут.

        Args:
            route_id: Идентификатор маршрута.
            body: Тело входного сообщения.
            headers: Заголовки входного сообщения.
            context: Runtime context.

        Returns:
            Exchange[Any]: Итоговый Exchange.

        Raises:
            RouteDisabledError: Маршрут заблокирован feature-флагом.
            KeyError: Маршрут не зарегистрирован.
        """
        pipeline = route_registry.get(route_id)
        return await self._engine.execute(
            pipeline, body=body, headers=headers, context=context
        )

    @staticmethod
    def list_routes() -> tuple[str, ...]:
        """Список всех зарегистрированных маршрутов."""
        return route_registry.list_routes()

    @staticmethod
    def list_enabled_routes() -> tuple[str, ...]:
        """Список маршрутов, доступных для выполнения."""
        return route_registry.list_enabled_routes()

    @staticmethod
    def list_disabled_routes() -> tuple[str, ...]:
        """Список маршрутов, заблокированных feature-флагом."""
        return route_registry.list_disabled_routes()

    @staticmethod
    def get_feature_flags() -> dict[str, str]:
        """Маппинг route_id → feature_flag."""
        return route_registry.get_route_feature_flags()

    @staticmethod
    def toggle_feature_flag(flag_name: str, *, enable: bool) -> None:
        """Включает/отключает feature-флаг.

        Args:
            flag_name: Имя feature-флага.
            enable: ``True`` — маршруты доступны,
                ``False`` — заблокированы.
        """
        route_registry.toggle_feature_flag(flag_name, enable=enable)


def get_dsl_service() -> DslService:
    """
    Возвращает facade DSL.
    """
    return DslService()
