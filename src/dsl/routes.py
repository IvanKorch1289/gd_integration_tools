from app.dsl.builder import RouteBuilder
from app.dsl.engine.exchange import Exchange
from app.dsl.registry import route_registry

__all__ = ("register_dsl_routes",)


def register_dsl_routes() -> None:
    """
    Регистрирует все DSL-маршруты приложения.

    Правила:
    - только декларация маршрутов;
    - без side effects кроме route_registry.register(...);
    - без HTTP/FastAPI-specific логики;
    - идемпотентность на уровне route_id overwrite допустима.
    """

    tech_send_email_route = (
        RouteBuilder.from_(
            route_id="tech.send_email",
            source="internal:tech.send_email",
            description="DSL-маршрут отправки email",
        )
        .set_header("x-route-id", "tech.send_email")
        .set_property("domain", "tech")
        .dispatch_action("tech.send_email", payload_factory=_email_payload_factory)
        .build()
    )

    route_registry.register(tech_send_email_route)


def _email_payload_factory(exchange: Exchange[dict]) -> dict:
    """
    Собирает payload для команды отправки email.

    Args:
        exchange: Текущий Exchange.

    Returns:
        dict: Нормализованный payload.
    """
    body = exchange.in_message.body or {}
    if not isinstance(body, dict):
        return {}

    return {
        "recipient": body.get("recipient"),
        "subject": body.get("subject"),
        "body": body.get("body"),
    }
