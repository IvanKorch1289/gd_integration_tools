from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Request

from app.core.enums.invocation import BrokerKind
from app.schemas.invocation import ActionCommandMetaSchema, InvocationOptionsSchema

__all__ = (
    "PayloadFactory",
    "MetaFactory",
    "EventPublishSpec",
    "InvocationSpec",
    "default_payload_factory",
    "build_http_command_meta",
)


PayloadFactory = Callable[[dict[str, Any], Request | None], dict[str, Any]]
MetaFactory = Callable[[dict[str, Any], Request | None], ActionCommandMetaSchema]


@dataclass(slots=True)
class EventPublishSpec:
    """
    Спецификация публикации action-команды в broker.
    """

    action: str
    broker: BrokerKind
    destination: str
    payload_factory: PayloadFactory
    meta_factory: MetaFactory | None = None


@dataclass(slots=True)
class InvocationSpec:
    """
    DSL-описание invocation-поведения action.

    Attributes:
        model: Pydantic-схема invocation options.
        source_fields: Поля, извлекаемые из endpoint kwargs.
        include_invocation_in_service_call: Передавать ли invoke в service method.
        invocation_argument_name: Имя аргумента invocation в service method.
        event: Спецификация публикации в broker.
    """

    model: type[InvocationOptionsSchema] = InvocationOptionsSchema
    source_fields: tuple[str, ...] = ("mode", "delay_seconds", "cron")
    include_invocation_in_service_call: bool = False
    invocation_argument_name: str = "invoke"
    event: EventPublishSpec | None = None


def default_payload_factory(
    source_kwargs: dict[str, Any], request: Request | None
) -> dict[str, Any]:
    """
    Возвращает payload без преобразований.
    """
    return dict(source_kwargs)


def build_http_command_meta(
    source_kwargs: dict[str, Any], request: Request | None
) -> ActionCommandMetaSchema:
    """
    Формирует meta для action-команды из HTTP-контекста.
    """
    return ActionCommandMetaSchema(
        source="http", request_path=request.url.path if request is not None else None
    )
