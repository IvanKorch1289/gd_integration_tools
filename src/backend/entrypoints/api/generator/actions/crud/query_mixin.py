from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.entrypoints.api.generator.actions.crud._protocol import (
        _CrudMixinProtocol,
    )
    from src.backend.entrypoints.api.generator.specs import CrudSpec

from inspect import Parameter

from fastapi import Request, status
from fastapi_filter import FilterDepends
from fastapi_pagination import Params

from src.backend.core.enums.ordering import OrderingTypeChoices
from src.backend.entrypoints.api.generator.reflection import (
    make_signature,
    query_parameter,
    request_parameter,
)


class QueryMixin:
    """CRUD query registrars (filter) для CrudMixin. S58 W1 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _CrudMixinProtocol

    def _register_filter(self: "_CrudMixinProtocol", spec: CrudSpec) -> None:
        """Выполнить операцию  register filter."""
        filter_class = spec.filter_class
        if filter_class is None:
            return

        async def endpoint(
            request: Request,
            page: int | None = None,
            size: int | None = None,
            filter: Any = None,
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
                filter=filter,
                by=by,
                order=getattr(order, "value", order),
                pagination=pagination,
            )

        endpoint.__name__ = f"{spec.name}_filter"
        endpoint.__doc__ = f"Фильтрация объектов ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            query_parameter("page", int | None, None, "Номер страницы."),
            query_parameter(
                "size", int | None, None, "Количество элементов на странице."
            ),
            Parameter(
                name="filter",
                kind=Parameter.KEYWORD_ONLY,
                annotation=filter_class,
                default=FilterDepends(filter_class),
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
            path=spec.filter_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_filter",
            summary="Получить объекты по фильтру",
            description=f"Возвращает отфильтрованные объекты ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
