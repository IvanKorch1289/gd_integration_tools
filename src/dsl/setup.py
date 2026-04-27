from src.dsl.commands.setup import register_action_handlers
from src.dsl.routes import register_dsl_routes

__all__ = ("bootstrap_dsl",)


def _register_adapters() -> None:
    """Регистрирует протокольные адаптеры.

    Вызывается после регистрации handlers и маршрутов.
    Конкретные адаптеры добавляются по мере реализации
    протоколов (SOAP, gRPC, WebSocket, Kafka и т.д.).
    """


def bootstrap_dsl() -> None:
    """Централизованный bootstrap DSL-слоя.

    Порядок важен:
        1. Регистрация action-обработчиков.
        2. Регистрация DSL-маршрутов (опираются на handlers).
        3. Инициализация протокольных адаптеров.
    """
    register_action_handlers()
    register_dsl_routes()
    _register_adapters()
