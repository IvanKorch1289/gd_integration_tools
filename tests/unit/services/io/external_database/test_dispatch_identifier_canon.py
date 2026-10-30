"""ADR-0400: единый канон валидации SQL-идентификаторов (ADR-0365).

Дефект: ``services/io/external_database/dispatch_mixin.py`` содержал
СВОЙ regex допустимых идентификаторов (``_IDENT_RE`` / ``_BIND_NAME_RE``) —
4-я реализация одного и того же правила. ADR-0365 требует один канон:
``core/utils/sql_identifiers.py``.

Тесты:
1. канон принимает ``name`` / ``schema.name`` / ``db.schema.name`` и
   отклоняет кавычки, пробелы, спецсимволы, 4+ сегмента;
2. ``dispatch_mixin`` не дублирует regex и использует канон;
3. поведение dispatch не изменилось: недопустимое имя → ``DatabaseError``
   с прежним текстом, валидное ``schema.name`` → выполняется SQL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.enums.external_db import (
    ExternalDBObjectMeta,
    ExternalDBObjectTypeChoices,
)
from src.backend.core.errors import DatabaseError
from src.backend.core.utils.sql_identifiers import validate_qualified_identifier
from src.backend.services.io.external_database.dispatch_mixin import DispatchMixin

_DISPATCH_MIXIN = Path(DispatchMixin.__module__.replace(".", "/") + ".py")


# ─────────────────────────── канон ───────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "value", ["users", "public_users", "_tmp1", "schema.users", "db.schema.users"]
)
def test_canonical_accepts_qualified_identifiers(value: str) -> None:
    """Канон принимает 1..3 сегмента обычных идентификаторов."""
    assert validate_qualified_identifier(value, context="test") == value


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "users; DROP TABLE users",
        'users"',
        "users name",
        "schema.users.extra.part",
        "1users",
        "",
    ],
)
def test_canonical_rejects_unsafe_identifiers(value: str) -> None:
    """Канон отклоняет спецсимволы, пробелы и лишние сегменты."""
    with pytest.raises(ValueError, match="Недопустимый SQL identifier"):
        validate_qualified_identifier(value, context="test")


# ─────────────────────── dispatch_mixin ───────────────────────


@pytest.mark.unit
def test_dispatch_mixin_has_no_local_identifier_regex() -> None:
    """Локальные regex идентификаторов в dispatch_mixin удалены."""
    source = Path(DispatchMixin.__module__.replace(".", "/") + ".py")
    content = source.read_text(encoding="utf-8")
    assert "_IDENT_RE" not in content, "локальный regex идентификаторов не удалён"
    assert "_BIND_NAME_RE" not in content, "локальный regex bind-имён не удалён"
    assert "sql_identifiers" in content, "dispatch_mixin не использует канон"


class _FakeResult:
    """Фейковый результат SQLAlchemy."""

    def mappings(self) -> _FakeResult:
        """Вернуть себя (имитация ``Result.mappings()``).

        Returns:
            Тот же объект.
        """
        return self

    def all(self) -> list[dict[str, Any]]:
        """Вернуть пустой набор строк.

        Returns:
            Пустой список.
        """
        return []


class _FakeSession:
    """Фейковая AsyncSession: только ``execute``."""

    def __init__(self) -> None:
        self.execute = AsyncMock(return_value=_FakeResult())
        self.commit = AsyncMock()


def _meta(name: str, *, schema: str | None = None) -> ExternalDBObjectMeta:
    """Собрать метаданные внешнего объекта.

    Args:
        name: Имя объекта.
        schema: Опциональная схема.

    Returns:
        Экземпляр :class:`ExternalDBObjectMeta`.
    """
    return ExternalDBObjectMeta(
        profile_name="pg_1",
        schema=schema,
        object_name=name,
        object_type=ExternalDBObjectTypeChoices.view,
    )


@pytest.mark.asyncio
async def test_dispatch_rejects_unsafe_identifier_with_database_error() -> None:
    """Недопустимое имя → DatabaseError (поведение пакета сохранено)."""
    mixin = DispatchMixin()
    session = _FakeSession()
    meta = _meta("users; DROP TABLE users")

    with pytest.raises(DatabaseError, match="Недопустимый SQL identifier"):
        await mixin._execute_view(session, meta)

    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_accepts_qualified_identifier() -> None:
    """Валидное ``schema.name`` проходит и попадает в SQL."""
    mixin = DispatchMixin()
    session = _FakeSession()
    meta = _meta("users", schema="public")

    await mixin._execute_view(session, meta)

    assert session.execute.await_count == 1
    statement = session.execute.await_args.args[0]
    assert "public.users" in str(statement)
