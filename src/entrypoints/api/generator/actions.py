import inspect
from inspect import Parameter, Signature
from typing import Any, Awaitable, Callable, Sequence

from fastapi import APIRouter, Request, status
from fastapi_filter import FilterDepends
from fastapi_pagination import Params
from pydantic import BaseModel

from src.core.actions.spec_to_metadata import action_spec_to_metadata
from src.core.enums.ordering import OrderingTypeChoices
from src.dsl.commands.action_registry import action_handler_registry
from src.entrypoints.api.generator.marshaller import (
    decorate_endpoint,
    extract_invocation_kwargs,
    prepare_call_kwargs,
)
from src.entrypoints.api.generator.reflection import (
    body_parameter,
    build_invocation_parameters,
    build_model_parameters,
    make_signature,
    path_parameter,
    query_parameter,
    request_parameter,
    required_query_parameter,
)
from src.entrypoints.api.generator.specs import (
    ActionSpec,
    CrudSpec,
    HttpMethod,
    RouteDecorator,
)
from src.schemas.invocation import (
    InvocationOptionsSchema,
    InvocationResultSchema,
    InvokeMode,
)

__all__ = ("ActionSpec", "CrudSpec", "ActionRouterBuilder")


def _resolve_action_bus_service():
    """Lazy resolve action-bus сервиса через DI provider.

    Wave 6.5a: вместо прямого импорта ``infrastructure.external_apis.action_bus``
    используется ``core.di.providers.get_action_bus_service_provider`` —
    это сохраняет lazy-семантику (модуль может отсутствовать в
    усечённой dev_light-сборке) и убирает layer violation.
    """
    from src.core.di.providers import get_action_bus_service_provider

    return get_action_bus_service_provider()


class ActionRouterBuilder:
    """Компилятор DSL -> FastAPI routes."""

    def __init__(self, router: APIRouter) -> None:
        self.router = router

    def add_action(self, spec: ActionSpec) -> None:
        endpoint = self._build_action_endpoint(spec)
        endpoint = decorate_endpoint(endpoint, spec.decorators)

        response_model = spec.response_model
        if spec.invocation is not None:
            if response_model is not None:
                response_model = response_model | InvocationResultSchema
            else:
                response_model = Any | InvocationResultSchema

        self.router.add_api_route(
            path=spec.path,
            endpoint=endpoint,
            methods=[spec.method],
            name=spec.name,
            summary=spec.summary,
            description=spec.description,
            status_code=spec.status_code,
            response_model=response_model,
            dependencies=list(spec.dependencies),
            responses=spec.responses,
            tags=list(spec.tags) or None,
        )

        # Wave 14.1.B: автоматически регистрируем расширенные
        # метаданные action в ``action_handler_registry``. Сам handler
        # привязывается отдельно через ``setup.register_action_handlers``
        # (исторически), либо может быть привязан позже — здесь мы
        # сохраняем только metadata (``handler=None``), чтобы не
        # перезаписать уже существующую привязку.
        metadata = action_spec_to_metadata(spec)
        action_handler_registry.register_with_metadata(
            action=spec.name, handler=None, metadata=metadata
        )

    def add_actions(self, specs: Sequence[ActionSpec]) -> APIRouter:
        for spec in specs:
            self.add_action(spec)
        return self.router

    def add_crud_resource(self, spec: CrudSpec) -> APIRouter:
        if spec.include_get_all:
            self._register_get_all(spec)
        if spec.include_get_by_id:
            self._register_get_by_id(spec)
        if spec.include_get_first_or_last:
            self._register_get_first_or_last(spec)
        if spec.include_create:
            self._register_create(spec)
        if spec.include_create_many:
            self._register_create_many(spec)
        if spec.include_update:
            self._register_update(spec)
        if spec.include_delete:
            self._register_delete(spec)
        if spec.include_versions and spec.version_schema is not None:
            self._register_all_versions(spec)
            self._register_latest_version(spec)
        if spec.include_restore:
            self._register_restore(spec)
        if spec.include_changes:
            self._register_changes(spec)
        if spec.include_filter and spec.filter_class is not None:
            self._register_filter(spec)

        return self.router

    def add_crud_resources(self, specs: Sequence[CrudSpec]) -> APIRouter:
        for spec in specs:
            self.add_crud_resource(spec)
        return self.router

    # ------------------------------------------------------------------ #
    # Action endpoint builder
    # ------------------------------------------------------------------ #

    def _build_action_endpoint(self, spec: ActionSpec) -> Callable[..., Awaitable[Any]]:
        async def endpoint(request: Request, **kwargs: Any) -> Any:
            service = spec.service_getter()
            service_method = getattr(service, spec.service_method)

            call_kwargs = prepare_call_kwargs(spec=spec, request=request, kwargs=kwargs)
            invoke_options, direct_kwargs = extract_invocation_kwargs(
                spec=spec, call_kwargs=call_kwargs
            )

            async def direct_call() -> Any:
                method_kwargs = dict(direct_kwargs)
                if (
                    spec.invocation is not None
                    and spec.invocation.include_invocation_in_service_call
                    and invoke_options is not None
                ):
                    method_kwargs[spec.invocation.invocation_argument_name] = (
                        invoke_options
                    )
                result = service_method(**method_kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result

            is_delegated = False

            if spec.invocation is not None:
                is_scheduled = invoke_options is not None and (
                    invoke_options.delay_seconds is not None
                    or invoke_options.cron is not None
                )
                wants_event = (
                    invoke_options is not None
                    and invoke_options.mode == InvokeMode.event
                )

                if (wants_event or is_scheduled) and spec.invocation.event is None:
                    raise ValueError(
                        f"Action '{spec.name}' does not support event invocation."
                    )

                if spec.invocation.event is not None and (wants_event or is_scheduled):
                    bus_result = await _resolve_action_bus_service().invoke(
                        request=request,
                        invoke=invoke_options or InvocationOptionsSchema(),
                        publish_spec=spec.invocation.event,
                        direct_call=direct_call,
                        source_kwargs=direct_kwargs,
                    )
                    result = bus_result
                    is_delegated = True
                else:
                    result = await direct_call()
            else:
                result = await direct_call()

            if is_delegated:
                return InvocationResultSchema.model_validate(result)

            if spec.response_handler is not None:
                handled_result = spec.response_handler(result, direct_kwargs)
                if inspect.isawaitable(handled_result):
                    return await handled_result
                return handled_result

            return result

        endpoint.__signature__ = self._build_action_signature(spec)  # type: ignore[attr-defined]
        endpoint.__name__ = spec.name
        endpoint.__doc__ = (
            spec.description
            or f"Сгенерированный action endpoint для '{spec.service_method}'."
        )
        return endpoint

    @staticmethod
    def _build_action_signature(spec: ActionSpec) -> Signature:
        parameters: list[Parameter] = [request_parameter()]
        parameters.extend(build_model_parameters(spec.path_model, source="path"))
        parameters.extend(build_model_parameters(spec.query_model, source="query"))

        if spec.invocation is not None:
            parameters.extend(build_invocation_parameters(spec.invocation))

        if spec.body_model is not None:
            parameters.append(
                body_parameter(
                    "payload",
                    spec.body_model,
                    spec.body_model.__doc__ or "Тело запроса.",
                )
            )

        return make_signature(*parameters, return_annotation=Any)

    # ------------------------------------------------------------------ #
    # CRUD endpoint builders
    # ------------------------------------------------------------------ #

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
        async def endpoint(
            request: Request,
            page: int | None = None,
            size: int | None = None,
            by: str = spec.default_order_by,
            order: OrderingTypeChoices = OrderingTypeChoices.ascending,
        ) -> Any:
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

    def _register_get_by_id(self, spec: CrudSpec) -> None:
        async def endpoint(request: Request, **kwargs: Any) -> Any:
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

    def _register_get_first_or_last(self, spec: CrudSpec) -> None:
        async def endpoint(
            request: Request,
            limit: int = 1,
            by: str = spec.default_order_by,
            order: OrderingTypeChoices = OrderingTypeChoices.ascending,
        ) -> Any:
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
        async def endpoint(request: Request, payload: BaseModel) -> Any:
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

    def _register_create_many(self, spec: CrudSpec) -> None:
        async def endpoint(request: Request, payloads: list[BaseModel]) -> Any:
            service = spec.service_getter()
            data_list = [item.model_dump(exclude_none=True) for item in payloads]
            return await service.add_many(data_list=data_list)

        endpoint.__name__ = f"{spec.name}_create_many"
        endpoint.__doc__ = f"Создаёт несколько объектов ресурса '{spec.name}'."
        endpoint.__signature__ = make_signature(  # type: ignore[attr-defined]
            request_parameter(),
            body_parameter(
                "payloads",
                list[spec.schema_in],  # type: ignore[name-defined]
                f"Список объектов ресурса '{spec.name}'.",
            ),
        )

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

    def _register_update(self, spec: CrudSpec) -> None:
        async def endpoint(request: Request, payload: BaseModel, **kwargs: Any) -> Any:
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

    def _register_delete(self, spec: CrudSpec) -> None:
        async def endpoint(request: Request, **kwargs: Any) -> None:
            service = spec.service_getter()
            await service.delete(
                key=spec.id_field_name, value=kwargs[spec.id_param_name]
            )
            return None

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

    def _register_all_versions(self, spec: CrudSpec) -> None:
        async def endpoint(request: Request, **kwargs: Any) -> Any:
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
        async def endpoint(request: Request, **kwargs: Any) -> Any:
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
        async def endpoint(request: Request, **kwargs: Any) -> Any:
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
        async def endpoint(request: Request, **kwargs: Any) -> Any:
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
