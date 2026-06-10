"""CRUD mixin for ActionRouterBuilder (S49 W3 extraction).

Extracted from ``actions.py`` god-file (986 LOC → 251 LOC main + 232 LOC crud).
14 ``_register_*`` methods + class-level ``_CRUD_VERB_TO_SERVICE_METHOD`` mapping.

MRO composition: ``ActionRouterBuilder → CrudMixin → object`` (per ADR-0107).
"""

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


class CrudMixin:
    """CRUD route registration mixin.

    14 ``_register_*`` methods extracted from ``ActionRouterBuilder`` god-class.
    Composed via MRO: ``ActionRouterBuilder → CrudMixin → object`` (per ADR-0107).

    ``router`` attribute is owned by :class:`ActionRouterBuilder`; declared
    here only для mypy cross-MRO type-narrowing.
    """

    router: APIRouter
    _CRUD_VERB_TO_SERVICE_METHOD: dict[str, str] = {
        "list": "get",
        "get": "get",
        "create": "add",
        "create_many": "add_many",
        "update": "update",
        "delete": "delete",
    }

    @classmethod
    def _register_crud_action_metadata(
        cls,
        *,
        spec: CrudSpec,
        verb: str,
        method: HttpMethod,
        path: str,
        description: str,
        input_model: type[BaseModel] | None,
        output_model: type[BaseModel] | None,
    ) -> str:
        """Регистрирует Tier 1 action для CRUD-роута: handler + metadata.

        Wave 1.1 (Roadmap V10): каждый CRUD-роут, создаваемый
        :class:`ActionRouterBuilder`, дополнительно регистрирует
        соответствующий action в ``action_handler_registry`` с
        ``tier=1``-семантикой. Идентификатор формируется по конвенции
        F.8 ``"<resource>.<verb>"``.

        Регистрация:

        * ``register_with_metadata`` сохраняет :class:`ActionMetadata`
          (transports/side_effect/idempotent/tags) для Gateway/Developer
          portal;
        * ``register`` привязывает handler через ``service_getter`` +
          метод BaseService по конвенции (см.
          :attr:`_CRUD_VERB_TO_SERVICE_METHOD`). Если action с тем же
          именем уже зарегистрирован (например, ``orders.get`` из
          ``setup.register_action_handlers``) — повторная регистрация
          перезаписывает handler идентичной семантикой (idempotent).

        Args:
            spec: CRUD-описание ресурса.
            verb: Глагол action ("list", "get", "create", "create_many",
                "update", "delete").
            method: HTTP-метод роута для вывода ``side_effect``/
                ``idempotent`` через REST-конвенцию.
            path: Полный path роута (для трассировки/документации).
            description: Описание для OpenAPI и developer portal.
            input_model: Pydantic-модель payload (тело или путь).
            output_model: Pydantic-модель ответа.

        Returns:
            Сформированный ``action_id``.
        """
        action_id = f"{spec.name}.{verb}"
        side_effect = "read" if method.upper() == "GET" else "write"
        idempotent = method.upper() in {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}
        metadata = ActionMetadata(
            action=action_id,
            description=description,
            input_model=input_model,
            output_model=output_model,
            transports=("http", "grpc", "graphql"),
            side_effect=side_effect,
            idempotent=idempotent,
            tags=tuple(spec.tags),
        )
        action_handler_registry.register_with_metadata(
            action=action_id, handler=None, metadata=metadata
        )
        service_method = cls._CRUD_VERB_TO_SERVICE_METHOD.get(verb)
        if service_method is not None:
            action_handler_registry.register(
                action=action_id,
                service_getter=spec.service_getter,
                service_method=service_method,
                payload_model=input_model,
            )
        return action_id

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

    def _register_create(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register create."""

        async def endpoint(request: Request, payload: BaseModel) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.add(data=payload.model_dump(exclude_none=True))

        endpoint.__name__ = f"{spec.name}_create"
        endpoint.__doc__ = f"Создаёт новый объект ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            body_parameter(
                "payload", spec.schema_in, spec.schema_in.__doc__ or "Тело запроса."
            ),
        )
        self._register_route(
            path=spec.create_path,
            endpoint=endpoint,
            method="POST",
            name=f"{spec.name}_create",
            summary="Добавить объект",
            description=f"Создаёт новый объект ресурса '{spec.name}'.",
            status_code_=status.HTTP_201_CREATED,
            response_model=spec.schema_out,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="create",
            method="POST",
            path=spec.create_path,
            description=f"Создаёт новый объект ресурса '{spec.name}'.",
            input_model=spec.schema_in,
            output_model=spec.schema_out,
        )

    def _register_create_many(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register create many."""

        async def endpoint(request: Request, payloads: list[BaseModel]) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            data_list = [item.model_dump(exclude_none=True) for item in payloads]
            return await service.add_many(data_list=data_list)

        endpoint.__name__ = f"{spec.name}_create_many"
        endpoint.__doc__ = f"Создаёт несколько объектов ресурса '{spec.name}'."
        schema_in = spec.schema_in
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            body_parameter(
                "payloads",
                list[schema_in],  # type: ignore[valid-type]
                f"Список объектов ресурса '{spec.name}'.",
            ),
        )  # type: ignore[name-defined]
        self._register_route(
            path=spec.create_many_path,
            endpoint=endpoint,
            method="POST",
            name=f"{spec.name}_create_many",
            summary="Добавить несколько объектов",
            description=f"Создаёт несколько объектов ресурса '{spec.name}'.",
            status_code_=status.HTTP_201_CREATED,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="create_many",
            method="POST",
            path=spec.create_many_path,
            description=f"Создаёт несколько объектов ресурса '{spec.name}'.",
            input_model=spec.schema_in,
            output_model=None,
        )

    def _register_update(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register update."""

        async def endpoint(request: Request, payload: BaseModel, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.update(
                key=spec.id_field_name,
                value=kwargs[spec.id_param_name],
                data=payload.model_dump(exclude_none=True),
            )

        endpoint.__name__ = f"{spec.name}_update"
        endpoint.__doc__ = f"Обновляет объект ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
            body_parameter(
                "payload", spec.schema_in, spec.schema_in.__doc__ or "Тело запроса."
            ),
        )
        self._register_route(
            path=spec.update_path,
            endpoint=endpoint,
            method="PUT",
            name=f"{spec.name}_update",
            summary="Изменить объект по ID",
            description=f"Обновляет объект ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=spec.schema_out,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="update",
            method="PUT",
            path=spec.update_path,
            description=f"Обновляет объект ресурса '{spec.name}'.",
            input_model=spec.schema_in,
            output_model=spec.schema_out,
        )

    def _register_delete(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register delete."""

        async def endpoint(request: Request, **kwargs: Any) -> None:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            await service.delete(
                key=spec.id_field_name, value=kwargs[spec.id_param_name]
            )
            return

        endpoint.__name__ = f"{spec.name}_delete"
        endpoint.__doc__ = f"Удаляет объект ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )
        self._register_route(
            path=spec.delete_path,
            endpoint=endpoint,
            method="DELETE",
            name=f"{spec.name}_delete",
            summary="Удалить объект по ID",
            description=f"Удаляет объект ресурса '{spec.name}'.",
            status_code_=status.HTTP_204_NO_CONTENT,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )
        self._register_crud_action_metadata(
            spec=spec,
            verb="delete",
            method="DELETE",
            path=spec.delete_path,
            description=f"Удаляет объект ресурса '{spec.name}'.",
            input_model=None,
            output_model=None,
        )

    def _register_all_versions(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register all versions."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.get_all_object_versions(
                object_id=kwargs[spec.id_param_name],
                order=OrderingTypeChoices.ascending.value,
            )

        endpoint.__name__ = f"{spec.name}_all_versions"
        endpoint.__doc__ = f"Возвращает все версии объекта ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )
        self._register_route(
            path=spec.all_versions_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_all_versions",
            summary="Получить версии объекта",
            description=f"Возвращает все версии объекта ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )

    def _register_latest_version(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register latest version."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.get_latest_object_version(
                object_id=kwargs[spec.id_param_name]
            )

        endpoint.__name__ = f"{spec.name}_latest_version"
        endpoint.__doc__ = f"Возвращает последнюю версию объекта ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )
        self._register_route(
            path=spec.latest_version_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_latest_version",
            summary="Получить последнюю версию объекта",
            description=f"Возвращает последнюю версию объекта ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=spec.version_schema,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )

    def _register_restore(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register restore."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.restore_object_to_version(
                object_id=kwargs[spec.id_param_name],
                transaction_id=kwargs["transaction_id"],
            )

        endpoint.__name__ = f"{spec.name}_restore"
        endpoint.__doc__ = f"Восстанавливает объект ресурса '{spec.name}' до версии."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
            required_query_parameter(
                "transaction_id", int, "Идентификатор транзакции версии."
            ),
        )
        self._register_route(
            path=spec.restore_path,
            endpoint=endpoint,
            method="POST",
            name=f"{spec.name}_restore",
            summary="Восстановить объект до версии",
            description=f"Восстанавливает объект ресурса '{spec.name}' до указанной версии.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )

    def _register_changes(self, spec: CrudSpec) -> None:
        """Выполнить операцию  register changes."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            return await service.get_object_changes(
                object_id=kwargs[spec.id_param_name]
            )

        endpoint.__name__ = f"{spec.name}_changes"
        endpoint.__doc__ = f"Возвращает изменения объекта ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )
        self._register_route(
            path=spec.changes_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_changes",
            summary="Получить изменения объекта",
            description=f"Возвращает историю изменений объекта ресурса '{spec.name}'.",
            status_code_=status.HTTP_200_OK,
            response_model=None,
            dependencies=spec.dependencies,
            tags=spec.tags,
            decorators=spec.decorators,
        )

    def _register_filter(self, spec: CrudSpec) -> None:
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
