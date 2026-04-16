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
        """
        pipeline = route_registry.get(route_id)
        return await self._engine.execute(
            pipeline, body=body, headers=headers, context=context
        )


def get_dsl_service() -> DslService:
    """
    Возвращает facade DSL.
    """
    return DslService()
