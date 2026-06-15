from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from typing import Final

from pydantic import BaseModel

from src.backend.core.di.providers import get_external_session_manager_provider
from src.backend.core.enums.external_db import (
    ExternalDBObjectChoices,
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


class CoreMixin:
    """core execute flow (execute BIG 59 LOC, _validate_request, _build_db_params) для ExternalDatabaseService. S63 W4 extraction."""

    __slots__ = ()

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
