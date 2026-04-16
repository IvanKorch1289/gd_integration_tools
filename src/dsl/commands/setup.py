from app.dsl.commands.registry import action_handler_registry
from app.schemas.base import EmailSchema
from app.services.tech import get_tech_service

__all__ = ("register_action_handlers",)


def register_action_handlers() -> None:
    """
    Регистрирует все action-handlers приложения.

    Важно:
    - функция должна быть идемпотентной;
    - вызывается на startup приложения;
    - здесь регистрируются только runtime-команды,
      а не HTTP-роуты и не CRUD-генерация.
    """

    action_handler_registry.register(
        action="tech.send_email",
        service_getter=get_tech_service,
        service_method="send_email",
        payload_model=EmailSchema,
    )
