"""Structural protocol for ExternalDatabaseService mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и методы, чтобы
mypy видел ``self.logger``, ``self._validate_identifier`` и т.д.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.core.enums.external_db import ExternalDBObjectMeta
from src.backend.services.io.external_database.state import PreparedDBParameter


class _ExternalDatabaseProtocol(Protocol):
    """Общий контракт для CoreMixin / DispatchMixin / ValidationMixin / BuildMixin / ProfileMixin."""

    logger: Any

    def _validate_identifier(self, value: str, *, context: str) -> str: ...

    def _validate_bind_name(self, value: str, *, context: str) -> str: ...

    def _validate_response(self, meta: ExternalDBObjectMeta, result: Any) -> Any: ...

    def _build_arguments_sql(
        self, meta: ExternalDBObjectMeta, prepared_params: list[PreparedDBParameter]
    ) -> str: ...

    def _to_execute_params(
        self, prepared_params: list[PreparedDBParameter]
    ) -> dict[str, Any]: ...

    def _resolve_bind_name(self, param_meta: Any, index: int) -> str: ...

    def _get_profile_settings(self, profile_name: str) -> Any: ...

    async def _execute_by_type(
        self,
        session: Any,
        db_type: Any,
        meta: ExternalDBObjectMeta,
        prepared_params: list[PreparedDBParameter],
        execute_params: dict[str, Any],
    ) -> Any: ...
