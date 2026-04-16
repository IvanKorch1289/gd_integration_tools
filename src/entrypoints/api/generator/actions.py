import inspect
from dataclasses import dataclass, field
from inspect import Parameter, Signature
from typing import Any, Awaitable, Callable, Literal, Sequence

from fastapi import APIRouter, Body, Path, Query, Request, status
from fastapi_filter import FilterDepends
from fastapi_pagination import Params
from pydantic import BaseModel

from app.core.enums.ordering import OrderingTypeChoices
from app.entrypoints.api.generator.invocation import InvocationSpec
from app.infrastructure.external_apis.action_bus import get_action_bus_service
from app.schemas.invocation import (
    InvocationOptionsSchema,
    InvocationResultSchema,
    InvokeMode,
)

__all__ = ("ActionSpec", "CrudSpec", "ActionRouterBuilder")


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ServiceFactory = Callable[[], Any]
RouteDecorator = Callable[
    [Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]
]
ResponseHandler = Callable[[Any, dict[str, Any]], Any | Awaitable[Any]]


@dataclass(slots=True)
class ActionSpec:
    """
    Декларативное описание action-роута.
    """

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
    """
    DSL-описание CRUD-ресурса.
    """

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


class ActionRouterBuilder:
    """
    Компилятор DSL -> FastAPI routes.
    """

    def __init__(self, router: APIRouter) -> None:
        self.router = router

    def add_action(self, spec: ActionSpec) -> None:
        endpoint = self._build_action_endpoint(spec)
        endpoint = self._decorate_endpoint(endpoint, spec.decorators)

        response_model = spec.response_model
        if spec.invocation is not None:
            # Если action поддерживает invocation, OpenAPI должен знать,
            # что может вернуться как целевая модель, так и InvocationResultSchema.
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

    def _build_action_endpoint(self, spec: ActionSpec) -> Callable[..., Awaitable[Any]]:
        async def endpoint(request: Request, **kwargs: Any) -> Any:
            service = spec.service_getter()
            service_method = getattr(service, spec.service_method)

            call_kwargs = self._prepare_call_kwargs(
                spec=spec, request=request, kwargs=kwargs
            )

            invoke_options, direct_kwargs = self._extract_invocation_kwargs(
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

            # Флаг, был ли вызов отправлен в шину
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
                    bus_result = await get_action_bus_service().invoke(
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

            # Если мы опубликовали задачу в шину, возвращаем InvocationResultSchema.
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

    def _build_action_signature(self, spec: ActionSpec) -> Signature:
        parameters: list[Parameter] = [
            Parameter(
                name="request", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
            )
        ]

        parameters.extend(self._build_model_parameters(spec.path_model, source="path"))
        parameters.extend(
            self._build_model_parameters(spec.query_model, source="query")
        )

        if spec.invocation is not None:
            parameters.extend(self._build_invocation_parameters(spec.invocation))

        if spec.body_model is not None:
            parameters.append(
                Parameter(
                    name="payload",
                    kind=Parameter.KEYWORD_ONLY,
                    annotation=spec.body_model,
                    default=Body(
                        ..., description=(spec.body_model.__doc__ or "Тело запроса.")
                    ),
                )
            )

        return Signature(parameters=parameters, return_annotation=Any)

    @staticmethod
    def _build_model_parameters(
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

    @staticmethod
    def _build_invocation_parameters(spec: InvocationSpec) -> list[Parameter]:
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

    @staticmethod
    def _prepare_call_kwargs(
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

    @staticmethod
    def _extract_invocation_kwargs(
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

    @staticmethod
    def _decorate_endpoint(
        endpoint: Callable[..., Awaitable[Any]], decorators: Sequence[RouteDecorator]
    ) -> Callable[..., Awaitable[Any]]:
        decorated = endpoint
        for decorator in reversed(decorators):
            decorated = decorator(decorated)
        return decorated

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
        endpoint = self._decorate_endpoint(endpoint, decorators)

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

    @staticmethod
    def _request_parameter() -> Parameter:
        return Parameter(
            name="request", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        )

    @staticmethod
    def _path_parameter(name: str, annotation: Any, description: str) -> Parameter:
        return Parameter(
            name=name,
            kind=Parameter.KEYWORD_ONLY,
            annotation=annotation,
            default=Path(..., description=description),
        )

    @staticmethod
    def _query_parameter(
        name: str, annotation: Any, default_value: Any, description: str
    ) -> Parameter:
        return Parameter(
            name=name,
            kind=Parameter.KEYWORD_ONLY,
            annotation=annotation,
            default=Query(default_value, description=description),
        )

    @staticmethod
    def _required_query_parameter(
        name: str, annotation: Any, description: str
    ) -> Parameter:
        return Parameter(
            name=name,
            kind=Parameter.KEYWORD_ONLY,
            annotation=annotation,
            default=Query(..., description=description),
        )

    @staticmethod
    def _body_parameter(name: str, annotation: Any, description: str) -> Parameter:
        return Parameter(
            name=name,
            kind=Parameter.KEYWORD_ONLY,
            annotation=annotation,
            default=Body(..., description=description),
        )

    @staticmethod
    def _signature(*parameters: Parameter, return_annotation: Any = Any) -> Signature:
        return Signature(
            parameters=list(parameters), return_annotation=return_annotation
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._query_parameter("page", int | None, None, "Номер страницы."),
            self._query_parameter(
                "size", int | None, None, "Количество элементов на странице."
            ),
            self._query_parameter("by", str, spec.default_order_by, "Поле сортировки."),
            self._query_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._query_parameter("limit", int, 1, "Количество возвращаемых объектов."),
            self._query_parameter("by", str, spec.default_order_by, "Поле сортировки."),
            self._query_parameter(
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
            description=(
                f"Возвращает первые или последние объекты ресурса '{spec.name}'."
            ),
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._body_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._body_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
            self._body_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
        )

        self._register_route(
            path=spec.latest_version_path,
            endpoint=endpoint,
            method="GET",
            name=f"{spec.name}_latest_version",
            summary="Получить последнюю версию объекта",
            description=(f"Возвращает последнюю версию объекта ресурса '{spec.name}'."),
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
                spec.id_param_name, spec.id_param_type, "Идентификатор объекта."
            ),
            self._required_query_parameter(
                "transaction_id", int, "Идентификатор транзакции версии."
            ),
        )

        self._register_route(
            path=spec.restore_path,
            endpoint=endpoint,
            method="POST",
            name=f"{spec.name}_restore",
            summary="Восстановить объект до версии",
            description=(
                f"Восстанавливает объект ресурса '{spec.name}' до указанной версии."
            ),
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._path_parameter(
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
        endpoint.__signature__ = self._signature(  # type: ignore[attr-defined]
            self._request_parameter(),
            self._query_parameter("page", int | None, None, "Номер страницы."),
            self._query_parameter(
                "size", int | None, None, "Количество элементов на странице."
            ),
            Parameter(
                name="filter",
                kind=Parameter.KEYWORD_ONLY,
                annotation=filter_class,
                default=FilterDepends(filter_class),
            ),
            self._query_parameter("by", str, spec.default_order_by, "Поле сортировки."),
            self._query_parameter(
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
