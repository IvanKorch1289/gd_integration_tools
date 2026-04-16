from app.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)
from app.dsl.engine.pipeline import Pipeline

__all__ = (
    "RouteRegistry",
    "route_registry",
    "ActionHandlerRegistry",
    "ActionHandlerSpec",
    "action_handler_registry",
)


class RouteRegistry:
    """
    Реестр DSL-маршрутов приложения.

    Хранит route_id -> Pipeline и предоставляет
    единый runtime-access для HTTP, stream и других entrypoints.
    """

    def __init__(self) -> None:
        self._routes: dict[str, Pipeline] = {}

    def register(self, pipeline: Pipeline) -> None:
        """
        Регистрирует маршрут.

        Args:
            pipeline: Готовый Pipeline.

        Raises:
            ValueError: Если route_id пустой.
        """
        route_id = pipeline.route_id.strip()
        if not route_id:
            raise ValueError("Route id must not be empty")

        self._routes[route_id] = pipeline

    def get(self, route_id: str) -> Pipeline:
        """
        Возвращает маршрут по route_id.

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            Pipeline: Найденный маршрут.

        Raises:
            KeyError: Если маршрут не зарегистрирован.
        """
        return self._routes[route_id]

    def get_optional(self, route_id: str) -> Pipeline | None:
        """
        Возвращает маршрут или None.

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            Pipeline | None: Найденный маршрут или None.
        """
        return self._routes.get(route_id)

    def is_registered(self, route_id: str) -> bool:
        """
        Проверяет наличие маршрута.

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            bool: Признак регистрации.
        """
        return route_id in self._routes

    def list_routes(self) -> tuple[str, ...]:
        """
        Возвращает список зарегистрированных маршрутов.

        Returns:
            tuple[str, ...]: Отсортированный список route_id.
        """
        return tuple(sorted(self._routes.keys()))

    def clear(self) -> None:
        """
        Очищает реестр маршрутов.
        """
        self._routes.clear()


route_registry = RouteRegistry()
