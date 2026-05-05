"""Request kwargs marshalling for action endpoints."""

from typing import Any, Awaitable, Callable, Sequence

from fastapi import Request
from pydantic import BaseModel

from src.backend.entrypoints.api.generator.specs import ActionSpec, RouteDecorator
from src.backend.schemas.invocation import InvocationOptionsSchema

__all__ = ("prepare_call_kwargs", "extract_invocation_kwargs", "decorate_endpoint")


def prepare_call_kwargs(
    spec: ActionSpec, request: Request, kwargs: dict[str, Any]
) -> dict[str, Any]:
    call_kwargs = dict(kwargs)

    payload = call_kwargs.pop("payload", None)
    if payload is not None:
        if isinstance(payload, BaseModel):
            payload_data = payload.model_dump(exclude_none=True)
        else:
            payload_data = payload

        if spec.body_argument_name:
            call_kwargs[spec.body_argument_name] = payload_data
        elif isinstance(payload_data, dict):
            call_kwargs.update(payload_data)
        else:
            call_kwargs["payload"] = payload_data

    if spec.request_argument_name:
        call_kwargs[spec.request_argument_name] = request

    if spec.argument_aliases:
        aliased_kwargs: dict[str, Any] = {}
        for key, value in call_kwargs.items():
            aliased_key = spec.argument_aliases.get(key, key)
            aliased_kwargs[aliased_key] = value
        call_kwargs = aliased_kwargs

    return call_kwargs


def extract_invocation_kwargs(
    spec: ActionSpec, call_kwargs: dict[str, Any]
) -> tuple[InvocationOptionsSchema | None, dict[str, Any]]:
    if spec.invocation is None:
        return None, dict(call_kwargs)

    direct_kwargs = dict(call_kwargs)
    invoke_payload: dict[str, Any] = {}

    for field_name in spec.invocation.source_fields:
        if field_name in direct_kwargs:
            invoke_payload[field_name] = direct_kwargs.pop(field_name)

    invoke_options = spec.invocation.model.model_validate(invoke_payload)
    return invoke_options, direct_kwargs


def decorate_endpoint(
    endpoint: Callable[..., Awaitable[Any]], decorators: Sequence[RouteDecorator]
) -> Callable[..., Awaitable[Any]]:
    decorated = endpoint
    for decorator in reversed(decorators):
        decorated = decorator(decorated)
    return decorated
