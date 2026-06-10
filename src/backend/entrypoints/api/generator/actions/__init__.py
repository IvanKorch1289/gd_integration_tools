import inspect
import os
from collections.abc import Awaitable, Callable, Sequence
from inspect import Parameter, Signature
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend.core.actions.spec_to_metadata import action_spec_to_metadata
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.entrypoints.api.generator.actions.crud import (
    CrudMixin,  # S49 W3: MRO composition per ADR-0107
)
from src.backend.entrypoints.api.generator.marshaller import (
    decorate_endpoint,
    extract_invocation_kwargs,
    prepare_call_kwargs,
)
from src.backend.entrypoints.api.generator.reflection import (
    body_parameter,
    build_invocation_parameters,
    build_model_parameters,
    make_signature,
    request_parameter,
)
from src.backend.entrypoints.api.generator.specs import ActionSpec, CrudSpec
from src.backend.schemas.invocation import (
    InvocationOptionsSchema,
    InvocationResultSchema,
    InvokeMode,
)

__all__ = ("ActionRouterBuilder", "ActionSpec", "CrudSpec")


def _resolve_action_bus_service():
    """Lazy resolve action-bus сервиса через DI provider.

    Wave 6.5a: вместо прямого импорта ``infrastructure.external_apis.action_bus``
    используется ``core.di.providers.get_action_bus_service_provider`` —
    это сохраняет lazy-семантику (модуль может отсутствовать в
    усечённой dev_light-сборке) и убирает layer violation.
    """
    from src.backend.core.di.providers import get_action_bus_service_provider

    return get_action_bus_service_provider()


_USE_DISPATCHER_ENV = "USE_ACTION_DISPATCHER_FOR_HTTP"


def _http_dispatcher_enabled() -> bool:
    """Проверяет глобальный feature flag ``USE_ACTION_DISPATCHER_FOR_HTTP``.

    Чтение env'а на каждый запрос — допустимо: оверхед минимальный,
    зато можно горячо переключать без рестарта при отладке.
    """
    return os.getenv(_USE_DISPATCHER_ENV, "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _should_use_dispatcher(spec: ActionSpec) -> bool:
    """Решает, использовать ли Gateway-цепочку для конкретного action.

    Wave 14.1 post-sprint-2 техдолг #6: per-action override
    глобального env-флага через поле ``ActionSpec.use_dispatcher``.

    Precedence:

    * ``spec.use_dispatcher is True`` — всегда через Gateway;
    * ``spec.use_dispatcher is False`` — всегда прямой путь
      (даже если глобальный flag = ON);
    * ``spec.use_dispatcher is None`` (дефолт) — следовать
      env-флагу ``USE_ACTION_DISPATCHER_FOR_HTTP``.

    Это даёт безопасную поэтапную миграцию: разработчик помечает
    ``use_dispatcher=True`` пилотную группу actions, остальные
    остаются на прямом пути до своей очереди.
    """
    override = getattr(spec, "use_dispatcher", None)
    if override is not None:
        return bool(override)
    return _http_dispatcher_enabled()


def _build_dispatcher_payload(call_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Сворачивает kwargs endpoint'а в плоский payload для dispatcher.

    ``prepare_call_kwargs`` уже распаковал body/path/query в общий dict;
    остаются только service-specific аргументы (без ``request``,
    которое не сериализуется и не нужно дисспетчеру).
    """
    payload: dict[str, Any] = {}
    for key, value in call_kwargs.items():
        if isinstance(value, Request):
            continue
        payload[key] = value
    return payload


def _action_result_to_response(result: Any) -> Any:
    """Маппит :class:`ActionResult` в FastAPI-friendly response.

    * ``success=True`` → возвращается ``result.data`` напрямую
      (FastAPI сам сериализует через response_model).
    * ``success=False`` → :class:`JSONResponse` с кодом ``400``
      для recoverable-ошибок и ``500`` для non-recoverable.
    """
    from src.backend.core.interfaces.action_dispatcher import ActionResult

    if not isinstance(result, ActionResult):
        return result
    if result.success:
        return result.data
    error = result.error
    code = "internal_error"
    message = "Action dispatch failed"
    details: dict[str, Any] | None = None
    status_code = 500
    if error is not None:
        code = error.code
        message = error.message
        details = dict(error.details) if error.details else None
        status_code = 400 if error.recoverable else 500
        if code == "action_not_found":
            status_code = 404
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    if result.metadata:
        body["metadata"] = dict(result.metadata)
    return JSONResponse(status_code=status_code, content=body)


async def _dispatch_via_gateway(
    *,
    action: str,
    request: Request,
    direct_kwargs: dict[str, Any],
    fallback: Callable[[], Awaitable[Any]],
) -> Any:
    """Делегирует вызов в :class:`ActionGatewayDispatcher` и маппит envelope.

    Если action не зарегистрирован в реестре или диспетчер недоступен —
    откатывается на ``fallback`` (старый прямой путь), чтобы feature-flag
    включение не ломало незарегистрированные эндпоинты.
    """
    from src.backend.core.di.contexts import make_dispatch_context
    from src.backend.core.di.providers import get_action_dispatcher_provider

    dispatcher = get_action_dispatcher_provider()
    if not dispatcher.is_registered(action):
        return await fallback()
    payload = _build_dispatcher_payload(direct_kwargs)
    correlation_id = request.headers.get("x-correlation-id") or request.headers.get(
        "x-request-id"
    )
    idempotency_key = request.headers.get("idempotency-key")
    context = make_dispatch_context(
        source="http",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        attributes={"method": request.method, "path": request.url.path},
    )
    envelope = await dispatcher.dispatch(action, payload, context)
    return _action_result_to_response(envelope)


class ActionRouterBuilder(CrudMixin):
    """Компилятор DSL -> FastAPI routes."""

    def __init__(self, router: APIRouter) -> None:
        """Выполнить операцию   init  ."""
        self.router = router

    def add_action(self, spec: ActionSpec) -> None:
        """Добавить action."""
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
        metadata = action_spec_to_metadata(spec)
        action_handler_registry.register_with_metadata(
            action=metadata.action, handler=None, metadata=metadata
        )

    def add_actions(self, specs: Sequence[ActionSpec]) -> APIRouter:
        """Добавить actions."""
        for spec in specs:
            self.add_action(spec)
        return self.router

    def add_crud_resource(self, spec: CrudSpec) -> APIRouter:
        """Добавить crud resource."""
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
        """Добавить crud resources."""
        for spec in specs:
            self.add_crud_resource(spec)
        return self.router

    def _build_action_endpoint(self, spec: ActionSpec) -> Callable[..., Awaitable[Any]]:
        """Выполнить операцию  build action endpoint."""

        async def endpoint(request: Request, **kwargs: Any) -> Any:
            """Выполнить операцию endpoint."""
            service = spec.service_getter()
            service_method = getattr(service, spec.service_method)
            call_kwargs = prepare_call_kwargs(spec=spec, request=request, kwargs=kwargs)
            invoke_options, direct_kwargs = extract_invocation_kwargs(
                spec=spec, call_kwargs=call_kwargs
            )

            async def direct_call() -> Any:
                """Выполнить операцию direct call."""
                method_kwargs = dict(direct_kwargs)
                if (
                    spec.invocation is not None
                    and spec.invocation.include_invocation_in_service_call
                    and (invoke_options is not None)
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
                elif _should_use_dispatcher(spec):
                    result = await _dispatch_via_gateway(
                        action=spec.action_id or spec.name,
                        request=request,
                        direct_kwargs=direct_kwargs,
                        fallback=direct_call,
                    )
                else:
                    result = await direct_call()
            elif _should_use_dispatcher(spec):
                result = await _dispatch_via_gateway(
                    action=spec.action_id or spec.name,
                    request=request,
                    direct_kwargs=direct_kwargs,
                    fallback=direct_call,
                )
            else:
                result = await direct_call()
            if is_delegated:
                return InvocationResultSchema.model_validate(result)
            if isinstance(result, JSONResponse):
                return result
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
        """Выполнить операцию  build action signature."""
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
