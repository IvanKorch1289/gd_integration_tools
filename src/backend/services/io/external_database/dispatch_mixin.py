from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.enums.external_db import (
    ExternalDBObjectMeta,
    ExternalDBObjectTypeChoices,
)
from src.backend.core.errors import DatabaseError
from src.backend.services.io.external_database.state import PreparedDBParameter

# IL-CRIT1.1: SQL Injection defence-in-depth (Security Layer 2 review).
#
# Даже при том, что `meta.qualified_name` / `param.db_name` / `param.bind_name`
# приходят из whitelist-enum `ExternalDBObjectChoices`, никогда не следует
# полагаться на один уровень защиты. Добавлен regex-guard для всех identifier-ов,
# которые попадают в динамический SQL. Если кто-то случайно / вредительски
# запишет в meta строку с пробелом / кавычкой / точкой с запятой — `DatabaseError`
# с понятным сообщением вместо выполнения неожиданного SQL.
#
# Формат identifier-а: `name` или `schema.name` или `db.schema.name`, где
# каждый сегмент — обычный SQL identifier без кавычек.
_IDENT_RE: Final = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"
)

# Bind-имена (после ":") должны быть простыми — без точек, без спецсимволов.
_BIND_NAME_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DispatchMixin:
    """DB type dispatch (_execute_by_type + 4 type-specific executors) для ExternalDatabaseService. S63 W4 extraction."""

    __slots__ = ()

    async def _execute_by_type(
        self,
        session: AsyncSession,
        db_type: DatabaseTypeChoices,
        meta: ExternalDBObjectMeta,
        prepared_params: list[PreparedDBParameter],
        execute_params: dict[str, Any],
    ) -> Any:
        """
        Разруливает выполнение по типу объекта.
        """
        if meta.object_type == ExternalDBObjectTypeChoices.query:
            return await self._execute_query(session, meta, execute_params)

        if meta.object_type == ExternalDBObjectTypeChoices.view:
            return await self._execute_view(session, meta)

        if meta.object_type == ExternalDBObjectTypeChoices.function:
            return await self._execute_function(
                session=session,
                db_type=db_type,
                meta=meta,
                prepared_params=prepared_params,
                execute_params=execute_params,
            )

        if meta.object_type == ExternalDBObjectTypeChoices.procedure:
            return await self._execute_procedure(
                session=session,
                db_type=db_type,
                meta=meta,
                prepared_params=prepared_params,
                execute_params=execute_params,
            )

        raise DatabaseError(
            message=f"Неподдерживаемый тип внешнего объекта: {meta.object_type}"
        )

    async def _execute_query(
        self,
        session: AsyncSession,
        meta: ExternalDBObjectMeta,
        execute_params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Выполняет whitelist-query.
        """
        if not meta.sql_text:
            raise DatabaseError(
                message=f"Для query '{meta.object_name}' не задан sql_text"
            )

        result = await session.execute(text(meta.sql_text), execute_params)
        return [dict(row) for row in result.mappings().all()]

    async def _execute_view(
        self, session: AsyncSession, meta: ExternalDBObjectMeta
    ) -> list[dict[str, Any]]:
        """
        Выполняет SELECT * FROM разрешённого view.
        """
        safe_name = self._validate_identifier(meta.qualified_name, context="view")
        sql = f"SELECT * FROM {safe_name}"  # safe_name провалидирован _validate_identifier (regex)  # noqa: S608  # internal query with controlled parameters
        result = await session.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]

    async def _execute_function(
        self,
        session: AsyncSession,
        db_type: DatabaseTypeChoices,
        meta: ExternalDBObjectMeta,
        prepared_params: list[PreparedDBParameter],
        execute_params: dict[str, Any],
    ) -> Any:
        """
        Выполняет разрешённую функцию.
        """
        safe_name = self._validate_identifier(meta.qualified_name, context="function")
        arguments_sql = self._build_arguments_sql(meta, prepared_params)

        if db_type == DatabaseTypeChoices.postgresql:
            if meta.returns_rows:
                sql = f"SELECT * FROM {safe_name}({arguments_sql})"  # safe_name из _validate_identifier, arguments_sql из _build_arguments_sql  # noqa: S608  # internal query with controlled parameters
                result = await session.execute(text(sql), execute_params)
                return result.mappings().all()

            sql = f"SELECT {safe_name}({arguments_sql}) AS result"  # safe_name из _validate_identifier, arguments_sql из _build_arguments_sql
            result = await session.execute(text(sql), execute_params)
            return result.scalar_one_or_none()

        if db_type == DatabaseTypeChoices.oracle:
            if meta.returns_rows:
                sql = f"SELECT * FROM {safe_name}({arguments_sql})"  # safe_name из _validate_identifier, arguments_sql из _build_arguments_sql  # noqa: S608  # internal query with controlled parameters
                result = await session.execute(text(sql), execute_params)
                return result.mappings().all()

            sql = f"SELECT {safe_name}({arguments_sql}) AS result FROM dual"  # safe_name из _validate_identifier, arguments_sql из _build_arguments_sql  # noqa: S608  # internal query with controlled parameters
            result = await session.execute(text(sql), execute_params)
            return result.scalar_one_or_none()

        raise DatabaseError(message=f"Неподдерживаемый тип БД для function: {db_type}")

    async def _execute_procedure(
        self,
        session: AsyncSession,
        db_type: DatabaseTypeChoices,
        meta: ExternalDBObjectMeta,
        prepared_params: list[PreparedDBParameter],
        execute_params: dict[str, Any],
    ) -> dict[str, str]:
        """
        Выполняет разрешённую процедуру.

        Для POST-запросов именно сюда обычно приходит body,
        который уже был:
        - провалидирован request_schema;
        - преобразован в параметры БД;
        - безопасно передан через bind-параметры.
        """
        safe_name = self._validate_identifier(meta.qualified_name, context="procedure")
        arguments_sql = self._build_arguments_sql(meta, prepared_params)

        if db_type == DatabaseTypeChoices.postgresql:
            sql = f"CALL {safe_name}({arguments_sql})"
        elif db_type == DatabaseTypeChoices.oracle:
            sql = f"BEGIN {safe_name}({arguments_sql}); END;"
        else:
            raise DatabaseError(
                message=f"Неподдерживаемый тип БД для procedure: {db_type}"
            )

        await session.execute(text(sql), execute_params)
        await session.commit()

        return {"status": "ok"}
