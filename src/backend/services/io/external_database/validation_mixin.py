from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from typing import Final

from src.backend.core.enums.external_db import ExternalDBObjectMeta
from src.backend.core.errors import DatabaseError

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


from src.backend.services.io.external_database._protocol import (
    _ExternalDatabaseProtocol,
)


class ValidationMixin(_ExternalDatabaseProtocol):
    """identifier + bind name + response validation для ExternalDatabaseService. S63 W4 extraction."""

    __slots__ = ()

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
