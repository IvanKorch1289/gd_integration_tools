"""Data-layer RouteBuilder contracts (W9 P2-13 split).

CRUD/batch/SQL/templates семейство — все операции над структурированными
данными: entity CRUD (entity_*/crud_*), batch-DB + in-memory KV
(batch_*/data_store_*), SQL DML/DQL (db_*), persistence (proc/file/S3/lookup),
Jinja2/PDF templates.

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_data.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


@_runtime_checkable
class _RouteEntityCrudProtocol(_Protocol):
    """Contract: entity CRUD операции (entity_*/crud_* aliases)."""

    def entity_create(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_get(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_delete(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_list(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_create(
        self,
        entity: str,
        *,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_read(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_update(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_delete(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_list(
        self,
        entity: str,
        *,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteBatchDataProtocol(_Protocol):
    """Contract: batch-DB + in-memory KV (batch_*/data_store_*)."""

    def batch_insert(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        profile: str = "default",
    ) -> Any: ...
    def batch_update(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> Any: ...
    def batch_delete(
        self,
        table: str,
        ids: list[Any] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> Any: ...
    def data_store_set(self, key: str, value: Any) -> Any: ...
    def data_store_get(
        self,
        key: str,
        *,
        default: Any = None,
        result_property: str = "data_store_value",
    ) -> Any: ...
    def data_store_delete(self, key: str) -> Any: ...
    def data_store(self, name: str = "default", backend: str = "memory") -> Any: ...


@_runtime_checkable
class _RouteDbProtocol(_Protocol):
    """Contract: SQL DML/DQL (db_query/db_insert/update/upsert/delete/execute_dml/external/jdbc)."""

    def db_query(self, sql: str, *, result_property: str = "db_result") -> Any: ...
    def db_insert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_update(
        self,
        table: str,
        data: dict[str, Any],
        where: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_upsert(
        self,
        table: str,
        data: dict[str, Any],
        conflict_keys: list[str],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def execute_dml(
        self,
        operation: str,
        table: str,
        *,
        dialect: str = "postgresql",
        data: dict[str, Any] | None = None,
        where: dict[str, Any] | None = None,
        conflict_keys: list[str] | None = None,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_delete(
        self,
        table: str,
        where: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> Any: ...
    def jdbc_query(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
    ) -> Any: ...


@_runtime_checkable
class _RoutePersistenceProtocol(_Protocol):
    """Contract: stored-proc + file/S3 + lookup + merge."""

    def db_call_procedure(
        self,
        profile: str,
        name: str,
        *,
        schema: str = "public",
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str = "postgres",
    ) -> Any: ...
    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> Any: ...
    def read_file(self, path: str | None = None, *, binary: bool = False) -> Any: ...
    def write_file(self, path: str | None = None, *, format: str = "auto") -> Any: ...
    def read_s3(self, bucket: str | None = None, key: str | None = None) -> Any: ...
    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> Any: ...
    def lookup(
        self, key_from: str, *, target: str, result_property: str = "lookup_result"
    ) -> Any: ...
    def merge(
        self,
        source_property: str,
        *,
        target_property: str = "merge_result",
        strategy: str = "merge_dicts",
    ) -> Any: ...


@_runtime_checkable
class _RouteTemplateProtocol(_Protocol):
    """Contract: Jinja2-шаблоны (sync + async DSL processors)."""

    def jinja_template(
        self,
        template_string: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> Any: ...
    def jinja_template_file(
        self,
        path: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> Any: ...
    def html_template(
        self,
        template: str,
        *,
        to: str = "body.html",
        context_from: str = "body",
        autoescape: bool = True,
    ) -> Any: ...
    def pdf_template(
        self,
        template: str,
        *,
        to: str = "body.pdf_bytes",
        page_size: str = "A4",
        font_size: int = 12,
    ) -> Any: ...
    def register_filter(self, name: str, fn: Any) -> Any: ...
    def template_render_str(
        self, template_str: str, context: dict[str, Any] | None = None
    ) -> str: ...
    def render_file(
        self, template_path: str, context: dict[str, Any] | None = None
    ) -> str: ...
