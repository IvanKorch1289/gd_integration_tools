"""Structural protocol for BaseService mixins.

Breaks the circular dependency between ``BaseService`` and its mixins and
lets mypy know which private attributes/helpers the mixins expect.
"""

from __future__ import annotations

from typing import Any, Protocol


class _BaseServiceProtocol(Protocol):
    """Common shape expected by BaseService mixins."""

    HelperMethods: type[Any]
    helper: Any
    repo: Any
    response_schema: Any
    request_schema: Any
    version_schema: Any
    table_name: str | None

    def _service_error_boundary(self) -> Any: ...

    def _entity_tag(self) -> str: ...

    def _table_tag(self) -> str | None: ...

    async def _invalidate_entity_cache(
        self, *, entity_id: Any | None = None, table_name: str | None = None
    ) -> None: ...
