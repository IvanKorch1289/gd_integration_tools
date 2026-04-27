from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.state.runtime import disabled_feature_flags
from src.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)

if TYPE_CHECKING:
    from src.dsl.engine.pipeline import Pipeline

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

    def list_enabled_routes(self) -> tuple[str, ...]:
        """
        Возвращает маршруты, доступные для выполнения.

        Исключает маршруты, чей feature_flag находится
        в ``disabled_feature_flags``.

        Returns:
            tuple[str, ...]: Отсортированный список route_id.
        """
        return tuple(
            sorted(
                rid
                for rid, pipeline in self._routes.items()
                if pipeline.feature_flag is None
                or pipeline.feature_flag not in disabled_feature_flags
            )
        )

    def list_disabled_routes(self) -> tuple[str, ...]:
        """
        Возвращает маршруты, заблокированные feature-флагом.

        Returns:
            tuple[str, ...]: Отсортированный список route_id.
        """
        return tuple(
            sorted(
                rid
                for rid, pipeline in self._routes.items()
                if pipeline.feature_flag is not None
                and pipeline.feature_flag in disabled_feature_flags
            )
        )

    def get_route_feature_flags(self) -> dict[str, str]:
        """
        Возвращает маппинг route_id → feature_flag для всех
        маршрутов, защищённых флагами.

        Returns:
            dict[str, str]: {route_id: feature_flag_name}.
        """
        return {
            rid: pipeline.feature_flag
            for rid, pipeline in sorted(self._routes.items())
            if pipeline.feature_flag is not None
        }

    @staticmethod
    def toggle_feature_flag(flag_name: str, *, enable: bool) -> None:
        """
        Включает или отключает feature-флаг.

        Args:
            flag_name: Имя feature-флага.
            enable: ``True`` — маршруты с этим флагом доступны;
                ``False`` — заблокированы.
        """
        if enable:
            disabled_feature_flags.discard(flag_name)
        else:
            disabled_feature_flags.add(flag_name)

    def clear(self) -> None:
        """
        Очищает реестр маршрутов.
        """
        self._routes.clear()


route_registry = RouteRegistry()
