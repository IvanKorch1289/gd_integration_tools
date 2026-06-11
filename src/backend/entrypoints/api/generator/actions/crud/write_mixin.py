from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


from fastapi import Request, status
from pydantic import BaseModel

from src.backend.core.enums.ordering import OrderingTypeChoices
from src.backend.entrypoints.api.generator.reflection import (
    body_parameter,
    make_signature,
    path_parameter,
    request_parameter,
)
from src.backend.entrypoints.api.generator.specs import CrudSpec


class WriteMixin:
    """CRUD write registrars (create, create_many, update, delete, all_versions) для CrudMixin. S58 W1 extraction."""

    __slots__ = ()

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
