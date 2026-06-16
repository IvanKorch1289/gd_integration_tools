from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import re
from typing import Final

from src.backend.core.config.settings import settings

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


class ProfileMixin(_ExternalDatabaseProtocol):
    """profile settings lookup для ExternalDatabaseService. S63 W4 extraction."""

    __slots__ = ()

    @staticmethod
    def _get_profile_settings(profile_name: str):
        """
        Возвращает resolved settings профиля внешней БД.
        """
        return settings.external_databases.get_profile(profile_name)
