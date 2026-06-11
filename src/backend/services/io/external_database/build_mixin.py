from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config.settings import settings
from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.di.providers import get_external_session_manager_provider
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.enums.external_db import (
    ExternalDBObjectChoices,
    ExternalDBObjectMeta,
    ExternalDBObjectTypeChoices,
    ExternalDBParameterMeta,
    ExternalDBParameterModeChoices,
)
from src.backend.core.errors import DatabaseError
from src.backend.core.logging import get_logger



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




class BuildMixin:
    """arguments SQL building + params conversion + bind name resolution для ExternalDatabaseService. S63 W4 extraction."""

    __slots__ = ()

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

