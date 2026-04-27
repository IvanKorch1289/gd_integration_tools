from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Sequence

from fastapi import status
from pydantic import BaseModel

from src.entrypoints.api.generator.invocation import InvocationSpec

__all__ = (
    "HttpMethod",
    "ServiceFactory",
    "RouteDecorator",
    "ResponseHandler",
    "ActionSpec",
    "CrudSpec",
)


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ServiceFactory = Callable[[], Any]
RouteDecorator = Callable[
    [Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]
]
ResponseHandler = Callable[[Any, dict[str, Any]], Any | Awaitable[Any]]


@dataclass(slots=True)
class ActionSpec:
    """Декларативное описание action-роута."""

    name: str
    method: HttpMethod
    path: str
    summary: str
    service_getter: ServiceFactory
    service_method: str

    description: str | None = None
    status_code: int = status.HTTP_200_OK

    path_model: type[BaseModel] | None = None
    query_model: type[BaseModel] | None = None
    body_model: type[BaseModel] | None = None
    body_argument_name: str | None = None

    response_model: type[BaseModel] | None = None
    dependencies: Sequence[Any] = field(default_factory=tuple)
    decorators: Sequence[RouteDecorator] = field(default_factory=tuple)
    responses: dict[int, Any] | None = None
    tags: Sequence[str] = field(default_factory=tuple)

    argument_aliases: dict[str, str] = field(default_factory=dict)
    response_handler: ResponseHandler | None = None
    request_argument_name: str | None = None
    invocation: InvocationSpec | None = None


@dataclass(slots=True)
class CrudSpec:
    """DSL-описание CRUD-ресурса."""

    name: str
    service_getter: ServiceFactory
    schema_in: type[BaseModel]
    schema_out: type[BaseModel] | None = None
    version_schema: type[BaseModel] | None = None

    filter_class: type | None = None
    dependencies: Sequence[Any] = field(default_factory=tuple)
    decorators: Sequence[RouteDecorator] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)

    id_param_name: str = "object_id"
    id_param_type: type = int
    id_field_name: str = "id"
    default_order_by: str = "id"

    include_get_all: bool = True
    include_get_by_id: bool = True
    include_get_first_or_last: bool = True
    include_create: bool = True
    include_create_many: bool = True
    include_update: bool = True
    include_delete: bool = True
    include_filter: bool = True
    include_versions: bool = True
    include_restore: bool = True
    include_changes: bool = True

    list_path: str = "/all/"
    by_id_path: str = "/id/{object_id}"
    first_or_last_path: str = "/first-or-last/"
    create_path: str = "/create/"
    create_many_path: str = "/create_many/"
    update_path: str = "/update/{object_id}"
    delete_path: str = "/delete/{object_id}"
    filter_path: str = "/filter/"
    all_versions_path: str = "/all_versions/{object_id}"
    latest_version_path: str = "/latest_version/{object_id}"
    restore_path: str = "/restore_to_version/{object_id}"
    changes_path: str = "/changes/{object_id}"
