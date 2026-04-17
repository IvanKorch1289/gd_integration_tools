"""Регистрация DSL-маршрутов приложения.

Автоматически создаёт маршрут для каждого зарегистрированного
action из ActionHandlerRegistry. После регистрации все actions
доступны через GraphQL, SOAP, WebSocket, SSE, Webhook и другие
протоколы без дополнительного кода.
"""

from app.dsl.builder import RouteBuilder
from app.dsl.commands.registry import action_handler_registry
from app.dsl.engine.exchange import Exchange
from app.dsl.registry import route_registry

__all__ = ("register_dsl_routes",)


def _default_payload_factory(exchange: Exchange[dict]) -> dict:
    """Извлекает payload из Exchange как dict."""
    body = exchange.in_message.body
    if isinstance(body, dict):
        return body
    return {}


def _register_action_route(action: str) -> None:
    """Создаёт и регистрирует DSL-маршрут для одного action."""
    domain = action.split(".")[0] if "." in action else action

    route = (
        RouteBuilder.from_(
            route_id=action,
            source=f"internal:{action}",
            description=f"DSL-маршрут: {action}",
        )
        .set_header("x-route-id", action)
        .set_property("domain", domain)
        .dispatch_action(action, payload_factory=_default_payload_factory)
        .build()
    )
    route_registry.register(route)


def register_dsl_routes() -> None:
    """Регистрирует DSL-маршруты для всех actions из ActionHandlerRegistry."""
    for action in action_handler_registry.list_actions():
        _register_action_route(action)
