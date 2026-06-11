from __future__ import annotations

"""ExternalDatabaseService package (S63 W4 decomp from external_database.py 492 LOC).

15 methods decomposed в 5 mixin files + state.py:
- ``core_mixin.py`` (3): execute (59 LOC, BIG), _validate_request, _build_db_params
- ``dispatch_mixin.py`` (5): _execute_by_type + 4 type-specific executors (query/view/function/procedure)
- ``validation_mixin.py`` (3): _validate_identifier, _validate_bind_name, _validate_response
- ``build_mixin.py`` (3): _build_arguments_sql, _to_execute_params, _resolve_bind_name
- ``profile_mixin.py`` (1): _get_profile_settings
- ``state.py``: PreparedDBParameter

Core (1) остается в __init__.py: __init__.

Backward-compat: ``from src.backend.services.io.external_database import ExternalDatabaseService`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from dataclasses import dataclass
from typing import Final

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


from src.backend.services.io.external_database.build_mixin import (
    BuildMixin,  # S63 W4: MRO
)
from src.backend.services.io.external_database.core_mixin import (
    CoreMixin,  # S63 W4: MRO
)
from src.backend.services.io.external_database.dispatch_mixin import (
    DispatchMixin,  # S63 W4: MRO
)
from src.backend.services.io.external_database.profile_mixin import (
    ProfileMixin,  # S63 W4: MRO
)
from src.backend.services.io.external_database.state import (
    PreparedDBParameter,  # S63 W4: re-export
)
from src.backend.services.io.external_database.validation_mixin import (
    ValidationMixin,  # S63 W4: MRO
)

__all__ = (
    "ExternalDatabaseService",
    "PreparedDBParameter",
    "get_external_db_service",
    "__getattr__",
)


class ExternalDatabaseService(
    CoreMixin, DispatchMixin, ValidationMixin, BuildMixin, ProfileMixin
):
    """External database service (5 mixins = 14 methods + 1 core)."""

    __slots__ = ()

    def __init__(self) -> None:
        self.logger = get_logger("services.io.external_database")


def get_external_db_service() -> ExternalDatabaseService:
    """Lazy accessor singleton ``ExternalDatabaseService``."""
    raise NotImplementedError  # заменяется декоратором


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``external_db_service``."""
    if name == "external_db_service":
        return get_external_db_service()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
