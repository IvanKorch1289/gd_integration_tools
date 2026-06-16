from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.entrypoints.api.generator.actions.crud._protocol import (
        _CrudMixinProtocol,
    )
    from src.backend.entrypoints.api.generator.specs import CrudSpec

from fastapi import Request, status

from src.backend.entrypoints.api.generator.reflection import (
    make_signature,
    path_parameter,
    request_parameter,
    required_query_parameter,
)


class VersioningMixin:
    """CRUD versioning registrars (latest_version, restore, changes) для CrudMixin. S58 W1 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _CrudMixinProtocol

    def _register_latest_version(self: "_CrudMixinProtocol", spec: CrudSpec) -> None:
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

    def _register_restore(self: "_CrudMixinProtocol", spec: CrudSpec) -> None:
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

    def _register_changes(self: "_CrudMixinProtocol", spec: CrudSpec) -> None:
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
