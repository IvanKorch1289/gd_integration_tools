import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config.settings import settings
from src.core.di.providers import get_external_session_manager_provider
from src.core.enums.database import DatabaseTypeChoices
from src.core.enums.external_db import (
    ExternalDBObjectChoices,
    ExternalDBObjectMeta,
    ExternalDBObjectTypeChoices,
    ExternalDBParameterMeta,
    ExternalDBParameterModeChoices,
)
from src.core.errors import DatabaseError

__all__ = ("external_db_service", "ExternalDatabaseService")


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


@dataclass(slots=True)
class PreparedDBParameter:
    """
    Подготовленный параметр для DB-вызова.

    bind_name:
        Имя bind-параметра в SQLAlchemy text(...).

    db_name:
        Имя аргумента в функции/процедуре БД.

    value:
        Итоговое значение после маппинга и валидации.
    """

    bind_name: str
    db_name: str
    value: Any


class ExternalDatabaseService:
    """
    Сервис выполнения разрешённых операций во внешних БД.

    Основные принципы:
    - выполняются только whitelist-объекты из ExternalDBObjectChoices;
    - request payload сначала валидируется Pydantic-схемой;
    - затем payload маппится в параметры вызова БД;
    - произвольный SQL извне не принимается.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("services.io.external_database")

    async def execute(
        self,
        db_object: ExternalDBObjectChoices,
        payload: dict[str, Any] | BaseModel | None = None,
    ) -> Any:
        """
        Унифицированная точка входа для вызова внешнего DB-объекта.

        Args:
            db_object: Разрешённый объект внешней БД из enum.
            payload: Входной payload. Обычно это body POST-запроса
                в виде dict или Pydantic-модели.

        Returns:
            Any: Результат выполнения операции после optional response validation.
        """
        meta = db_object.meta
        validated_payload = self._validate_request(meta, payload)
        prepared_params = self._build_db_params(meta, validated_payload)
        execute_params = self._to_execute_params(prepared_params)
        profile_settings = self._get_profile_settings(meta.profile_name)
        session_manager = get_external_session_manager_provider()(meta.profile_name)

        try:
            async with session_manager.create_session() as session:
                result = await self._execute_by_type(
                    session=session,
                    db_type=profile_settings.type,
                    meta=meta,
                    prepared_params=prepared_params,
                    execute_params=execute_params,
                )
        except DatabaseError:
            raise
        except Exception as exc:
            self.logger.error(
                "Ошибка выполнения внешнего DB-запроса",
                extra={
                    "profile_name": meta.profile_name,
                    "object_name": meta.object_name,
                    "object_type": meta.object_type.value,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise DatabaseError(
                message=(f"Ошибка выполнения внешнего объекта '{meta.qualified_name}'")
            ) from exc

        self.logger.info(
            "Внешний DB-запрос выполнен",
            extra={
                "profile_name": meta.profile_name,
                "object_name": meta.object_name,
                "object_type": meta.object_type.value,
            },
        )

        return self._validate_response(meta, result)

    def _validate_request(
        self, meta: ExternalDBObjectMeta, payload: dict[str, Any] | BaseModel | None
    ) -> dict[str, Any]:
        """
        Валидирует входной payload и возвращает обычный dict.

        Логика:
        - dict остаётся dict;
        - BaseModel преобразуется через model_dump();
        - при наличии request_schema используется model_validate();
        - при наличии body_root_field данные берутся из вложенного объекта.
        """
        if payload is None:
            raw_payload: dict[str, Any] = {}
        elif isinstance(payload, BaseModel):
            raw_payload = payload.model_dump(exclude_none=True)
        elif isinstance(payload, dict):
            raw_payload = payload
        else:
            raise DatabaseError(message="Неподдерживаемый тип payload")

        if meta.request_schema is not None:
            validated = meta.request_schema.model_validate(raw_payload)
            source = validated.model_dump(exclude_none=True)
        else:
            source = raw_payload

        if meta.body_root_field:
            nested = source.get(meta.body_root_field)
            if not isinstance(nested, dict):
                raise DatabaseError(
                    message=(
                        f"Ожидался объект в body_root_field='{meta.body_root_field}'"
                    )
                )
            return nested

        return source

    def _build_db_params(
        self, meta: ExternalDBObjectMeta, payload: dict[str, Any]
    ) -> list[PreparedDBParameter]:
        """
        Преобразует входной payload в параметры DB-вызова.

        Для function/procedure используется явное описание parameters.
        Для query, если parameters не заданы, payload передаётся как есть.
        Для view параметры запрещены.
        """
        if meta.object_type == ExternalDBObjectTypeChoices.view:
            if payload:
                raise DatabaseError(
                    message=(
                        f"View '{meta.qualified_name}' не принимает параметры. "
                        f"Если нужна фильтрация, опиши объект как query."
                    )
                )
            return []

        if (
            meta.object_type == ExternalDBObjectTypeChoices.query
            and not meta.parameters
        ):
            return [
                PreparedDBParameter(bind_name=name, db_name=name, value=value)
                for name, value in payload.items()
            ]

        prepared: list[PreparedDBParameter] = []

        for index, param_meta in enumerate(meta.parameters):
            value = payload.get(param_meta.body_field, param_meta.default)

            if value is None and param_meta.required and param_meta.default is None:
                raise DatabaseError(
                    message=(
                        f"Не найден обязательный параметр "
                        f"'{param_meta.body_field}' для '{meta.object_name}'"
                    )
                )

            if value is None and param_meta.exclude_if_none:
                continue

            bind_name = self._resolve_bind_name(param_meta, index)
            db_name = param_meta.db_name or param_meta.body_field

            prepared.append(
                PreparedDBParameter(bind_name=bind_name, db_name=db_name, value=value)
            )

        return prepared

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

    # -- IL-CRIT1.1: identifier validation (defence-in-depth) ---------

    @staticmethod
    def _validate_identifier(value: str, *, context: str) -> str:
        """Проверить, что identifier безопасен для интерполяции в SQL.

        Разрешены только обычные SQL identifiers: `name`, `schema.name`,
        `db.schema.name`. Кавычки, пробелы, спецсимволы — запрещены.

        Используется как defence-in-depth поверх whitelist-enum. Даже если
        в `ExternalDBObjectChoices` случайно попадёт строка со спецсимволом —
        код упадёт с понятной ошибкой, а не выполнит неожиданный SQL.
        """
        if not isinstance(value, str) or not _IDENT_RE.match(value):
            raise DatabaseError(
                message=(
                    f"Недопустимый SQL identifier в контексте '{context}': "
                    f"{value!r}. Ожидается name / schema.name / db.schema.name "
                    "без кавычек и спецсимволов."
                )
            )
        return value

    @staticmethod
    def _validate_bind_name(value: str, *, context: str) -> str:
        """Bind-параметр (после ':') — простой identifier без точек."""
        if not isinstance(value, str) or not _BIND_NAME_RE.match(value):
            raise DatabaseError(
                message=(
                    f"Недопустимый bind-параметр в '{context}': {value!r}. "
                    "Ожидается [A-Za-z_][A-Za-z0-9_]*."
                )
            )
        return value

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
        sql = f"SELECT * FROM {safe_name}"  # identifier провалидирован regex-ом
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
                sql = f"SELECT * FROM {safe_name}({arguments_sql})"
                result = await session.execute(text(sql), execute_params)
                return result.mappings().all()

            sql = f"SELECT {safe_name}({arguments_sql}) AS result"
            result = await session.execute(text(sql), execute_params)
            return result.scalar_one_or_none()

        if db_type == DatabaseTypeChoices.oracle:
            if meta.returns_rows:
                sql = f"SELECT * FROM {safe_name}({arguments_sql})"
                result = await session.execute(text(sql), execute_params)
                return result.mappings().all()

            sql = f"SELECT {safe_name}({arguments_sql}) AS result FROM dual"
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

    def _build_arguments_sql(
        self, meta: ExternalDBObjectMeta, prepared_params: list[PreparedDBParameter]
    ) -> str:
        """
        Строит SQL-фрагмент списка аргументов.

        Примеры:
        - named: p_id => :employee_id, p_force => :force
        - positional: :p0, :p1
        """
        if not prepared_params:
            return ""

        # IL-CRIT1.1: валидируем идентификаторы, которые попадают в SQL.
        # `db_name` и `bind_name` берутся из whitelist-enum, но применяем
        # defence-in-depth regex-проверку.
        for p in prepared_params:
            self._validate_bind_name(p.bind_name, context=f"bind_name:{p.db_name}")
            if meta.parameter_mode == ExternalDBParameterModeChoices.named:
                # db_name (имя аргумента функции) — тоже identifier.
                # Используем тот же bind-regex (имя без точек).
                self._validate_bind_name(p.db_name, context="db_name")

        if meta.parameter_mode == ExternalDBParameterModeChoices.named:
            return ", ".join(
                f"{param.db_name} => :{param.bind_name}" for param in prepared_params
            )

        return ", ".join(f":{param.bind_name}" for param in prepared_params)

    def _validate_response(self, meta: ExternalDBObjectMeta, result: Any) -> Any:
        """
        Валидирует ответ, если для объекта задан response_schema.
        """
        if meta.response_schema is None:
            return result

        if isinstance(result, list):
            return [
                meta.response_schema.model_validate(item).model_dump()
                for item in result
            ]

        if isinstance(result, dict):
            return meta.response_schema.model_validate(result).model_dump()

        return result

    @staticmethod
    def _resolve_bind_name(param_meta: ExternalDBParameterMeta, index: int) -> str:
        """
        Возвращает bind-имя параметра.
        """
        if param_meta.bind_name:
            return param_meta.bind_name

        if param_meta.db_name:
            return param_meta.db_name

        return f"p{index}_{param_meta.body_field}"

    @staticmethod
    def _to_execute_params(
        prepared_params: list[PreparedDBParameter],
    ) -> dict[str, Any]:
        """
        Преобразует prepared params в словарь для session.execute(...).
        """
        return {param.bind_name: param.value for param in prepared_params}

    @staticmethod
    def _get_profile_settings(profile_name: str):
        """
        Возвращает resolved settings профиля внешней БД.
        """
        return settings.external_databases.get_profile(profile_name)


external_db_service = ExternalDatabaseService()
