from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Awaitable, Callable, Sequence
from inspect import Parameter
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi_filter import FilterDepends
from fastapi_pagination import Params
from pydantic import BaseModel

from src.backend.core.enums.ordering import OrderingTypeChoices
from src.backend.core.interfaces.action_dispatcher import ActionMetadata
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.entrypoints.api.generator.marshaller import decorate_endpoint
from src.backend.entrypoints.api.generator.reflection import (
    body_parameter,
    make_signature,
    path_parameter,
    query_parameter,
    request_parameter,
    required_query_parameter,
)
from src.backend.entrypoints.api.generator.specs import (
    CrudSpec,
    HttpMethod,
    RouteDecorator,
)




class ReadMixin:
    """CRUD read registrars (route, get_all, get_by_id, get_first_or_last) для CrudMixin. S58 W1 extraction."""

    __slots__ = ()

    def _register_route(
        self,
        *,
        path: str,
        endpoint: Callable[..., Awaitable[Any]],
        method: HttpMethod,
        name: str,
        summary: str,
        description: str,
        status_code_: int,
        response_model: Any | None,
        dependencies: Sequence[Any],
        tags: Sequence[str],
        decorators: Sequence[RouteDecorator],
    ) -> None:
        """Выполнить операцию  register route."""
        endpoint = decorate_endpoint(endpoint, decorators)
        self.router.add_api_route(
            path=path,
            endpoint=endpoint,
            methods=[method],
            name=name,
            summary=summary,
            description=description,
            status_code=status_code_,
            response_model=response_model,
            dependencies=list(dependencies),
            tags=list(tags) or None,
        )



    def _register_get_all(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register get all."""

        async def endpoint(
            request: Request,
            page: int | None = None,
            size: int | None = None,
            by: str = spec.default_order_by,
            order: OrderingTypeChoices = OrderingTypeChoices.ascending,
        ) -> Any:
            """Выполнить операцию endpoint."""
            pagination = (
                Params(page=page, size=size)
                if page is not None and size is not None
                else None
            )
            service = spec.service_getter()
            return await service.get(
                pagination=pagination, by=by, order=getattr(order, "value", order)
            )

        endpoint.__name__ = f"{spec.name}_get_all"
        endpoint.__doc__ = f"Возвращает список объектов ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            query_parameter("page", int | None, None, "Номер страницы."),
            query_parameter(
                "size", int | None, None, "Количество элементов на странице."
            ),
            query_parameter("by", str, spec.default_order_by, "Поле сортировки."),
            query_parameter(
                "order",
                OrderingTypeChoices,
                OrderingTypeChoices.ascending,
                "Направление сортировки.",
            ),
        )
        self._register_route(
            path=spec.list_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_get_all",
            summary="Получить все объекты",
            description=f"Возвращает список объектов ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="list",
            method="GET",
            path=spec.list_path,
            description=f"Возвращает список объектов ресурса '{spec.name}'.",
            input_model=None,
            output_model=spec.schema_out,
        )



    def _register_get_by_id(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register get by id."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.get(
                key=spec.id_field_name, value=kwargs[spec.id_param_name]
            )

        endpoint.__name__ = f"{spec.name}_get_by_id"
        endpoint.__doc__ = f"Возвращает объект ресурса '{spec.name}' по ID."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )
        self._register_route(
            path=spec.by_id_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_get_by_id",
            summary="Получить объект по ID",
            description=f"Возвращает объект ресурса '{spec.name}' по идентификатору.",
            status_code_=status.HTTP_200_OK,
            response_model=spec.schema_out,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="get",
            method="GET",
            path=spec.by_id_path,
            description=f"Возвращает объект ресурса '{spec.name}' по идентификатору.",
            input_model=None,
            output_model=spec.schema_out,
        )



    def _register_get_first_or_last(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register get first or last."""

        async def endpoint(
            request: Request,
            limit: int = 1,
            by: str = spec.default_order_by,
            order: OrderingTypeChoices = OrderingTypeChoices.ascending,
        ) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.get_first_or_last_with_limit(
                limit=limit, by=by, order=getattr(order, "value", order)
            )

        endpoint.__name__ = f"{spec.name}_get_first_or_last"
        endpoint.__doc__ = (
            f"Возвращает первые или последние объекты ресурса '{spec.name}'."
        )
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            query_parameter("limit", int, 1, "Количество возвращаемых объектов."),
            query_parameter("by", str, spec.default_order_by, "Поле сортировки."),
            query_parameter(
                "order",
                OrderingTypeChoices,
                OrderingTypeChoices.ascending,
                "Направление сортировки.",
            ),
        )
        self._register_route(
            path=spec.first_or_last_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_get_first_or_last",
            summary="Получить первые или последние объекты",
            description=f"Возвращает первые или последние объекты ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )

