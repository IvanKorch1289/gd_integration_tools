from app.dsl.commands.setup import register_action_handlers
from app.dsl.routes import register_dsl_routes

__all__ = ("bootstrap_dsl",)


def bootstrap_dsl() -> None:
    """
    Централизованный bootstrap DSL-слоя.

    Порядок важен:
    1. регистрируем handlers;
    2. затем маршруты, которые на них опираются.
    """
    register_action_handlers()
    register_dsl_routes()
