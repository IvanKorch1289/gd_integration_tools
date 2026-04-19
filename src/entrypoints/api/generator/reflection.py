"""Signature/parameter building for action and CRUD endpoints."""

from inspect import Parameter, Signature
from typing import Any, Literal

from fastapi import Body, Path, Query
from pydantic import BaseModel

from app.entrypoints.api.generator.invocation import InvocationSpec
from app.schemas.invocation import InvokeMode

__all__ = (
    "build_model_parameters",
    "build_invocation_parameters",
    "request_parameter",
    "path_parameter",
    "query_parameter",
    "required_query_parameter",
    "body_parameter",
    "make_signature",
)


def build_model_parameters(
    model_cls: type[BaseModel] | None, source: Literal["path", "query"]
) -> list[Parameter]:
    if model_cls is None:
        return []

    parameters: list[Parameter] = []

    for field_name, field_info in model_cls.model_fields.items():
        annotation = field_info.annotation or Any
        description = field_info.description

        if source == "path":
            default = Path(..., description=description)
        else:
            if field_info.is_required():
                default = Query(..., description=description)
            else:
                default = Query(field_info.default, description=description)

        parameters.append(
            Parameter(
                name=field_name,
                kind=Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )

    return parameters


def build_invocation_parameters(spec: InvocationSpec) -> list[Parameter]:
    fields = set(spec.source_fields)
    parameters: list[Parameter] = []

    if "mode" in fields:
        parameters.append(
            Parameter(
                name="mode",
                kind=Parameter.KEYWORD_ONLY,
                annotation=InvokeMode,
                default=Query(
                    InvokeMode.direct,
                    description="Режим выполнения: direct или event.",
                ),
            )
        )

    if "delay_seconds" in fields:
        parameters.append(
            Parameter(
                name="delay_seconds",
                kind=Parameter.KEYWORD_ONLY,
                annotation=int | None,
                default=Query(
                    None, ge=1, description="Отложенное выполнение в секундах."
                ),
            )
        )

    if "cron" in fields:
        parameters.append(
            Parameter(
                name="cron",
                kind=Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=Query(
                    None, description="Cron-выражение для планового запуска."
                ),
            )
        )

    return parameters


def request_parameter() -> Parameter:
    from fastapi import Request

    return Parameter(
        name="request", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
    )


def path_parameter(name: str, annotation: Any, description: str) -> Parameter:
    return Parameter(
        name=name,
        kind=Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=Path(..., description=description),
    )


def query_parameter(
    name: str, annotation: Any, default_value: Any, description: str
) -> Parameter:
    return Parameter(
        name=name,
        kind=Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=Query(default_value, description=description),
    )


def required_query_parameter(
    name: str, annotation: Any, description: str
) -> Parameter:
    return Parameter(
        name=name,
        kind=Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=Query(..., description=description),
    )


def body_parameter(name: str, annotation: Any, description: str) -> Parameter:
    return Parameter(
        name=name,
        kind=Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=Body(..., description=description),
    )


def make_signature(*parameters: Parameter, return_annotation: Any = Any) -> Signature:
    return Signature(
        parameters=list(parameters), return_annotation=return_annotation
    )
