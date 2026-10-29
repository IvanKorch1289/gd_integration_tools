"""ADR-0386: сессия выставляет ``app.tenant_id`` для RLS-политик.

ORM-фильтр по ``tenant_id`` — первый рубеж изоляции, PostgreSQL RLS —
второй (defense-in-depth). RLS-политика читает GUC-параметр
``current_setting('app.tenant_id', true)``, поэтому приложение обязано
выставлять ``app.tenant_id`` в той же сессии, где применяется ORM-фильтр.

Проверяем session-event ``after_begin`` из
``core/tenancy/sqlalchemy_filter.py``:

* PostgreSQL + активный tenant → ``set_config('app.tenant_id', ...)``;
* другой диалект → ничего (RLS — PG-specific);
* нет tenant-контекста → ничего (fail-closed на стороне политики);
* ошибка БД → warning в лог, исключение наружу не уходит.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant
from src.backend.core.tenancy import sqlalchemy_filter as tf

pytestmark = pytest.mark.unit


def _connection(dialect: str = "postgresql") -> MagicMock:
    """Фейковое соединение с заданным диалектом."""
    connection = MagicMock()
    connection.dialect.name = dialect
    return connection


def _run_with_tenant(tenant_id: str, connection: MagicMock) -> None:
    """Вызвать session-event под tenant-контекстом."""
    token = bind_tenant(TenantContext(tenant_id=tenant_id))
    try:
        tf._set_tenant_scope_on_begin(None, None, connection)
    finally:
        unbind_tenant(token)


def test_after_begin_sets_app_tenant_id() -> None:
    """PostgreSQL + tenant → выставляется ``app.tenant_id``."""
    connection = _connection()

    _run_with_tenant("bank_a", connection)

    connection.execute.assert_called_once()
    statement, params = connection.execute.call_args[0]
    assert "set_config" in str(statement)
    assert "app.tenant_id" in str(statement)
    assert params == {"tenant_id": "bank_a"}


def test_after_begin_skips_non_postgres() -> None:
    """Другие диалекты (SQLite/Oracle/MSSQL) не трогаются."""
    connection = _connection("sqlite")

    _run_with_tenant("bank_a", connection)

    connection.execute.assert_not_called()


def test_after_begin_skips_without_tenant() -> None:
    """Без tenant-контекста GUC не выставляется."""
    connection = _connection()

    tf._set_tenant_scope_on_begin(None, None, connection)

    connection.execute.assert_not_called()


def test_after_begin_logs_error_and_does_not_raise() -> None:
    """Ошибка SET не должна ронять запрос — только warning."""
    connection = _connection()
    connection.execute.side_effect = RuntimeError("pg down")

    with pytest.MonkeyPatch.context() as patch:
        logger = MagicMock()
        patch.setattr(tf, "db_logger", logger)
        _run_with_tenant("bank_a", connection)

    logger.warning.assert_called_once()
    assert "app.tenant_id" in logger.warning.call_args[0][0]


def test_listener_is_registered_on_session() -> None:
    """``after_begin``-listener зарегистрирован на классе Session."""
    tf.apply_tenant_filter()

    assert event.contains(Session, "after_begin", tf._set_tenant_scope_on_begin)


def test_listener_fires_on_session_transaction() -> None:
    """Listener реально срабатывает при начале транзакции Session."""
    calls: list[object] = []
    original = tf._set_tenant_scope_on_begin

    def spy(session: object, transaction: object, connection: object) -> None:
        calls.append(connection)
        original(session, transaction, connection)  # type: ignore[arg-type]

    tf.apply_tenant_filter()
    event.remove(Session, "after_begin", original)
    event.listen(Session, "after_begin", spy)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
    finally:
        event.remove(Session, "after_begin", spy)
        event.listen(Session, "after_begin", original)
        engine.dispose()

    assert len(calls) == 1
