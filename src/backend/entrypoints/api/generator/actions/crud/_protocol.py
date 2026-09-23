from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from fastapi import APIRouter
    from pydantic import BaseModel

    from src.backend.entrypoints.api.generator.specs import (
        CrudSpec,
        HttpMethod,
        RouteDecorator,
    )


class _CrudMixinProtocol(Protocol):
    """Cross-mixin protocol for CrudMixin cluster."""

    router: APIRouter

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
    ) -> None: ...

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
    ) -> str: ...

    def _register_get_all(self, spec: CrudSpec) -> None: ...
    def _register_get_by_id(self, spec: CrudSpec) -> None: ...
    def _register_get_first_or_last(self, spec: CrudSpec) -> None: ...
    def _register_create(self, spec: CrudSpec) -> None: ...
    def _register_create_many(self, spec: CrudSpec) -> None: ...
    def _register_update(self, spec: CrudSpec) -> None: ...
    def _register_delete(self, spec: CrudSpec) -> None: ...
    def _register_all_versions(self, spec: CrudSpec) -> None: ...
    def _register_latest_version(self, spec: CrudSpec) -> None: ...
    def _register_restore(self, spec: CrudSpec) -> None: ...
    def _register_changes(self, spec: CrudSpec) -> None: ...
    def _register_filter(self, spec: CrudSpec) -> None: ...
