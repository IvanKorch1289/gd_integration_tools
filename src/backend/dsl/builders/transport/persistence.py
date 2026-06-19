"""Persistence mixin: db + file + storage методы.

Извлечено из TransportMixin в S84 W2 (B2, ADR-0107 pending).
9 методов: db_query, db_query_external, jdbc_query, db_call_procedure,
read_file, write_file, read_s3, write_s3, file_move.

Все методы используют ``self._add_lazy`` для lazy-import processors,
что держит cold-start overhead низким.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class PersistenceMixin:
    """Mixin: 9 db/file/storage методов (S84 W2 B2 extraction)."""

    __slots__ = ()

    def db_call_procedure(
        self,
        profile: str,
        name: str,
        *,
        schema: str = "public",
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str = "postgres",
    ) -> RouteBuilder:
        """K3 S5 W8 — вызвать stored procedure через ExternalDatabaseRegistry.

        Args:
            profile: Профиль внешней БД из ``settings.external_databases``.
            name: Имя процедуры.
            schema: Schema-префикс (default ``public``).
            params_from: ``body`` / ``properties`` / ``headers`` / ``none``.
            result_property: Куда положить result-set.
            dialect: ``postgres`` / ``mssql`` / ``oracle``.

        Returns:
            ``RouteBuilder`` для chain-продолжения.

        Example::

            (
                RouteBuilder.from_("orders.recalc", source="timer:60s")
                .db_call_procedure("oracle_prod", "recalc_credit_score")
                .build()
            )
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_call_procedure",
            "DbCallProcedureProcessor",
            profile=profile,
            name=name,
            schema=schema,
            params_from=params_from,
            result_property=result_property,
            dialect=dialect,
        )

    def db_query(self, sql: str, *, result_property: str = "db_result") -> RouteBuilder:
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "DatabaseQueryProcessor",
            sql=sql,
            result_property=result_property,
        )

    def db_insert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> RouteBuilder:
        """Safe INSERT через parameterized SQL (S95 W1).

        Auto-генерирует ``INSERT INTO "t" ("c1", "c2") VALUES (:c1, :c2)`` из
        ``data`` dict. Идентификаторы (table, columns) проходят whitelist
        (только [A-Za-z0-9_]); values — bind-params.

        Args:
            table: Table name.
            data: Column → value mapping.
            result_property: Куда положить result.

        Example::

            RouteBuilder.from_("orders.create", source="http:/orders")
                .db_insert("orders", {"id": "${body.id}", "status": "new"})
                .build()
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_crud",
            "DbCrudProcessor",
            operation="INSERT",
            table=table,
            data=data,
            result_property=result_property,
        )

    def db_upsert(
        self,
        table: str,
        data: dict[str, Any],
        conflict_keys: list[str],
        *,
        result_property: str = "db_crud_result",
    ) -> RouteBuilder:
        """Safe UPSERT (INSERT ... ON CONFLICT DO UPDATE, PostgreSQL).

        Args:
            table: Table name.
            data: Column → value mapping (включая conflict_keys).
            conflict_keys: PK/unique columns для conflict target.
            result_property: Куда положить result.

        Example::

            RouteBuilder.from_("users.sync", source="http:/users")
                .db_upsert(
                    "users",
                    {"id": "${body.id}", "name": "${body.name}"},
                    conflict_keys=["id"],
                )
                .build()
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_crud",
            "DbCrudProcessor",
            operation="UPSERT",
            table=table,
            data=data,
            conflict_keys=conflict_keys,
            result_property=result_property,
        )

    def db_delete(
        self,
        table: str,
        where: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> RouteBuilder:
        """Safe DELETE с explicit WHERE (S95 W1).

        ``where`` НЕ МОЖЕТ быть пустым (защита от accidental DELETE all).

        Args:
            table: Table name.
            where: Column → value mapping для WHERE clause.
            result_property: Куда положить result.

        Example::

            RouteBuilder.from_("orders.purge", source="timer:1d")
                .db_delete("orders", {"created_at_lt": "${now-30d}"})
                .build()
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_crud",
            "DbCrudProcessor",
            operation="DELETE",
            table=table,
            where=where,
            result_property=result_property,
        )

    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> RouteBuilder:
        """Выполняет произвольный SQL во внешней БД по profile-имени.

        Использует ``ExternalDatabaseRegistry`` (через DI) для получения
        async-сессии. Параметры берутся из body / properties / headers.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_query_external",
            "ExternalDbQueryProcessor",
            profile=profile,
            sql=sql,
            params_from=params_from,
            result_property=result_property,
            fetch=fetch,
            commit=commit,
        )

    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> RouteBuilder:
        """Copy/move/rename файлов."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "FileMoveProcessor",
            src=src,
            dst=dst,
            mode=mode,
        )

    def read_file(
        self, path: str | None = None, *, binary: bool = False
    ) -> RouteBuilder:
        """Чтение локального файла в body (text или bytes)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "FileReadProcessor",
            path=path,
            binary=binary,
        )

    def read_s3(
        self, bucket: str | None = None, key: str | None = None
    ) -> RouteBuilder:
        """Загрузка объекта из S3."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "S3ReadProcessor",
            bucket=bucket,
            key=key,
        )

    def write_file(
        self, path: str | None = None, *, format: str = "auto"
    ) -> RouteBuilder:
        """Запись body в файл. format: auto|json|csv|text."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "FileWriteProcessor",
            path=path,
            format=format,
        )

    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> RouteBuilder:
        """Выгрузка body в S3."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "S3WriteProcessor",
            bucket=bucket,
            key=key,
            content_type=content_type,
        )

    def jdbc_query(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
    ) -> RouteBuilder:
        """Execute arbitrary SQL against an external JDBC-compatible database profile.

        Uses ``ExternalDatabaseRegistry`` to obtain an async session for the
        given profile. SELECT queries return list[dict] via ``result_property``.
        INSERT/UPDATE/DELETE return affected row count (int) via ``result_property``.

        SQL is validated: DDL, DROP, GRANT, REVOKE, and multi-statement are blocked.
        Bind-parameters are sourced from body / properties / headers.

        Args:
            sql: SQL query with ``:name`` bind-parameters.
            profile: External database profile name.
            params_from: Source of bind-parameters — ``"body"`` (default) /
                ``"properties"`` / ``"headers"`` / ``"none"``.
            result_property: Exchange property key for the result.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.jdbc_query",
            "JdbcQueryProcessor",
            sql=sql,
            profile=profile,
            params_from=params_from,
            result_property=result_property,
        )

    def lookup(
        self,
        key_from: str,
        *,
        target: str,
        result_property: str = "lookup_result",
    ) -> "RouteBuilder":
        """Chainable lookup DSL method (S168 W10 P1-1, per master prompt).

        Сейчас: thin wrapper над ``data_store_get`` (in-memory dict lookup).
        Per master prompt: "first-class lookup-with-merge" pattern.
        Семантика: берёт key из property key_from, ищет в in-memory
        data_store, результат кладёт в result_property.

        Args:
            key_from: имя property в Exchange для ключа lookup.
            target: имя property для значения (для backward-compat).
            result_property: имя property для сохранения результата.

        Returns:
            RouteBuilder для chainable pattern.

        Example::

            builder.from_http("/users").lookup("user_id", target="user")
        """
        # Используем существующий DataStoreGetProcessor (data_store_get).
        # key_from — property с ключом, target — deprecated (для future
        # multi-source lookup).
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.data_store",
            "DataStoreGetProcessor",
            key_property=key_from,
            result_property=result_property,
        )

    def merge(
        self,
        source_property: str,
        *,
        target_property: str = "merge_result",
        strategy: str = "merge_dicts",
    ) -> "RouteBuilder":
        """Chainable merge DSL method (S168 W10 P1-1, per master prompt).

        Per master prompt: "first-class merge with on, strategy"
        pattern. Семантика: deep-merge dict из source_property в
        target_property (default body, или explicit target_property).
        Strategy ∈ {``merge_dicts``, ``list``, ``custom``} per
        :class:`MergeStrategy` (api_composition.py:157).

        Args:
            source_property: имя property с dict для merge.
            target_property: имя property для сохранения результата.
            strategy: merge strategy — ``merge_dicts`` (default, dict.update),
                ``list`` (list of dicts), ``custom`` (per processor).

        Example::

            builder.lookup("user_id").merge("user", target_property="body")
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.dict_ops",
            "PydashMergeProcessor",
            source_property=source_property,
            target_property=target_property,
            strategy=strategy,
        )
