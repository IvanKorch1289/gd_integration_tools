"""ADR-0418 — retry на сериализацию и SAVEPOINT в менеджере сессий.

Дефект волны 24 (кластер F3, medium):

* ``_RETRYABLE_CONNECT_ERRORS`` содержал только ``OperationalError`` /
  ``InterfaceError`` и срабатывал **только** на этапе ``connect`` —
  PostgreSQL-конфликты сериализации (SQLSTATE ``40001``) и дедлоки
  (``40P01``) не повторялись вовсе: операция падала с первой попытки;
* ``begin_nested`` — 0 совпадений по репозиторию: тело транзакции шло
  без SAVEPOINT, поэтому ошибка тела откатывала **всю** транзакцию.

Контракт фикса:

* повтор делается только на BEGIN-этапе (тело транзакции ещё не
  выполнялось → повтор безопасен), с экспоненциальным backoff;
* тело транзакции обёрнуто в SAVEPOINT: ошибка откатывает savepoint,
  а не всю транзакцию.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from src.backend.core.config.settings import settings
from src.backend.core.errors import DatabaseError
from src.backend.infrastructure.database.session_manager import (
    RETRYABLE_PG_CODES,
    DatabaseSessionManager,
    is_retryable_transaction_error,
    pg_sqlstate,
)

pytestmark = pytest.mark.unit


class _DriverSerializationError(Exception):
    """Ошибка драйвера PostgreSQL с кодом сериализации."""

    sqlstate = "40001"


class _DriverDeadlockError(Exception):
    """Ошибка драйвера PostgreSQL с кодом дедлока."""

    sqlstate = "40P01"


class _StubSavepoint:
    """SAVEPOINT-транзакция (рекордер вызовов)."""

    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False

    async def rollback(self) -> None:
        """Откат к SAVEPOINT."""
        self.rolled_back = True

    async def commit(self) -> None:
        """RELEASE SAVEPOINT."""
        self.committed = True


class _StubSession:
    """Сессия-заглушка: считает BEGIN / SAVEPOINT / commit / rollback."""

    def __init__(self, begin_nested_errors: list[BaseException] | None = None) -> None:
        self._begin_nested_errors = list(begin_nested_errors or [])
        self.begins = 0
        self.begin_nested_calls = 0
        self.savepoints: list[_StubSavepoint] = []
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self) -> bool:
        """Транзакция открыта?"""
        return self.begins > 0

    async def begin(self) -> _StubSavepoint:
        """BEGIN."""
        self.begins += 1
        return _StubSavepoint()

    async def begin_nested(self) -> _StubSavepoint:
        """SAVEPOINT (может бросить заданную ошибку)."""
        self.begin_nested_calls += 1
        if self._begin_nested_errors:
            raise self._begin_nested_errors.pop(0)
        savepoint = _StubSavepoint()
        self.savepoints.append(savepoint)
        return savepoint

    async def commit(self) -> None:
        """COMMIT."""
        self.commits += 1

    async def rollback(self) -> None:
        """ROLLBACK всей транзакции."""
        self.rollbacks += 1
        self.begins = 0


def _manager() -> DatabaseSessionManager:
    """Менеджер сессий с заглушкой (подключения к БД не происходит)."""
    return DatabaseSessionManager(session_maker=lambda: None, db_name="probe")  # type: ignore[arg-type]


# ── распознавание pgcode ──────────────────────────────────────────────────


def test_retryable_pg_codes_are_serialization_and_deadlock() -> None:
    """В наборе — только сериализация и дедлок."""
    assert RETRYABLE_PG_CODES == frozenset({"40001", "40P01"})


def test_pg_sqlstate_reads_driver_error() -> None:
    """SQLSTATE читается из ``orig`` обёртки SQLAlchemy."""
    exc = OperationalError("SELECT 1", {}, _DriverSerializationError("conflict"))

    assert pg_sqlstate(exc) == "40001"


def test_serialization_failure_is_retryable() -> None:
    """40001 (serialization_failure) — повторяемая ошибка."""
    exc = OperationalError("SELECT 1", {}, _DriverSerializationError("conflict"))

    assert is_retryable_transaction_error(exc) is True


def test_deadlock_is_retryable() -> None:
    """40P01 (deadlock_detected) — повторяемая ошибка."""
    exc = OperationalError("SELECT 1", {}, _DriverDeadlockError("deadlock"))

    assert is_retryable_transaction_error(exc) is True


def test_other_errors_are_not_retryable() -> None:
    """Прочие ошибки повторяться не должны."""
    exc = OperationalError("SELECT 1", {}, ValueError("syntax error"))

    assert is_retryable_transaction_error(exc) is False
    assert is_retryable_transaction_error(RuntimeError("boom")) is False


# ── retry на BEGIN-этапе ──────────────────────────────────────────────────


async def test_begin_stage_retries_on_serialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сериализационная ошибка на BEGIN-этапе → повтор с backoff."""
    monkeypatch.setattr(settings.database, "max_retries", 2)

    session = _StubSession(
        begin_nested_errors=[
            OperationalError("SAVEPOINT", {}, _DriverSerializationError("conflict"))
        ]
    )
    manager = _manager()

    async with manager.transaction(session):  # type: ignore[arg-type]
        pass

    # Попытка 1 — сериализационная ошибка; попытка 2 — успех.
    assert session.begin_nested_calls == 2
    assert len(session.savepoints) == 1
    assert session.savepoints[0].committed is True
    assert session.commits == 1


async def test_begin_stage_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Исчерпание попыток → ``DatabaseError`` (исходная ошибка БД)."""
    monkeypatch.setattr(settings.database, "max_retries", 1)

    session = _StubSession(
        begin_nested_errors=[
            OperationalError("SAVEPOINT", {}, _DriverSerializationError("conflict")),
            OperationalError("SAVEPOINT", {}, _DriverSerializationError("conflict")),
        ]
    )
    manager = _manager()

    with pytest.raises(DatabaseError):
        async with manager.transaction(session):  # type: ignore[arg-type]
            pass

    assert session.commits == 0


async def test_begin_stage_does_not_retry_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Несериализационная ошибка не повторяется."""
    monkeypatch.setattr(settings.database, "max_retries", 3)

    session = _StubSession(begin_nested_errors=[RuntimeError("boom")])
    manager = _manager()

    with pytest.raises(DatabaseError):
        async with manager.transaction(session):  # type: ignore[arg-type]
            pass

    assert session.savepoints == []


# ── SAVEPOINT на тело транзакции ──────────────────────────────────────────


async def test_body_error_rolls_back_savepoint_only() -> None:
    """Ошибка тела откатывает SAVEPOINT, а не всю транзакцию."""
    session = _StubSession()
    manager = _manager()

    with pytest.raises(DatabaseError):
        async with manager.transaction(session):  # type: ignore[arg-type]
            raise RuntimeError("business failure")

    assert len(session.savepoints) == 1
    assert session.savepoints[0].rolled_back is True
    assert session.savepoints[0].committed is False
    # Вся транзакция НЕ откатывается — внешний scope остаётся живым.
    assert session.rollbacks == 0
    assert session.commits == 0


async def test_successful_body_commits() -> None:
    """Успешное тело: RELEASE SAVEPOINT + COMMIT."""
    session = _StubSession()
    manager = _manager()

    async with manager.transaction(session):  # type: ignore[arg-type]
        pass

    assert len(session.savepoints) == 1
    assert session.savepoints[0].committed is True
    assert session.savepoints[0].rolled_back is False
    assert session.commits == 1


async def test_transaction_body_is_wrapped_in_savepoint() -> None:
    """Тело транзакции выполняется внутри SAVEPOINT."""
    session = _StubSession()
    manager = _manager()
    seen: list[Any] = []

    async with manager.transaction(session):  # type: ignore[arg-type]
        seen.append(len(session.savepoints))

    assert seen == [1]
