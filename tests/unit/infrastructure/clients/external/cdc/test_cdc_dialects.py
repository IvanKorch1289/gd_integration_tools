"""ADR-0384 — диалекты CDC: LIMIT/FETCH FIRST/TOP и LogMiner только для Oracle.

Волна 16 (кластер X5, дефект 6): polling всегда использовал
``LIMIT :limit`` (невалидно для Oracle/MSSQL/DB2), а LogMiner работал с
любой СУБД и не вызывал ``DBMS_LOGMNR.START_LOGMNR``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _LogMinerStrategy,
    _PollingStrategy,
    limit_clause,
)

# ════════════════════════════════════════════════════════════════════
# Fakes
# ════════════════════════════════════════════════════════════════════


class _FakeResult:
    """Пустой результат SELECT."""

    def fetchall(self) -> list[Any]:
        """Вернуть пустой список строк."""
        return []


class _FakeConnection:
    """Соединение, перехватывающее SQL."""

    def __init__(self, harness: _SqlHarness) -> None:
        self._harness = harness

    async def __aenter__(self) -> _FakeConnection:
        """Войти в контекст соединения."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Выйти из контекста соединения."""
        return False

    async def execute(self, query: Any, params: Any = None) -> _FakeResult:
        """Перехватить SQL и остановить polling-цикл."""
        self._harness.captured.append(str(query))
        self._harness.stop()
        return _FakeResult()


class _FakeDialect:
    """Диалект engine'а (SQLAlchemy-совместимый ``dialect.name``)."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeEngine:
    """Async engine с заданным диалектом."""

    def __init__(self, harness: _SqlHarness, dialect: str = "postgresql") -> None:
        self._harness = harness
        self.dialect = _FakeDialect(dialect)

    def connect(self) -> _FakeConnection:
        """Вернуть fake-соединение."""
        return _FakeConnection(self._harness)


class _FakeInitializer:
    """Заглушка ``DatabaseInitializer``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_async_engine(self) -> _FakeEngine:
        """Вернуть fake engine."""
        return self._engine


class _FakeRegistry:
    """Заглушка ``ExternalDatabaseRegistry``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_initializer(self, profile: str) -> _FakeInitializer:
        """Вернуть fake initializer."""
        return _FakeInitializer(self._engine)


class _SqlHarness:
    """Перехватчик исполняемого SQL."""

    def __init__(self) -> None:
        self.captured: list[str] = []
        self.sub: CDCSubscription | None = None

    def stop(self) -> None:
        """Остановить polling-цикл."""
        if self.sub is not None:
            self.sub.active = False


def _install_registry(
    monkeypatch: pytest.MonkeyPatch, harness: _SqlHarness, dialect: str
) -> None:
    """Подменить реестр внешних БД на fake с нужным диалектом."""
    engine = _FakeEngine(harness, dialect)
    registry = _FakeRegistry(engine)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.accessors."
        "get_external_db_registry",
        lambda: registry,
    )


async def _noop_dispatch(_sub: CDCSubscription, _event: CDCEvent) -> None:
    """Заглушка dispatch-callback."""
    return None


# ════════════════════════════════════════════════════════════════════
# 1. Диалектные ограничения выборки
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("postgresql", "LIMIT :limit"),
        ("mysql", "LIMIT :limit"),
        ("sqlite", "LIMIT :limit"),
        ("oracle", "FETCH FIRST :limit ROWS ONLY"),
        ("db2", "FETCH FIRST :limit ROWS ONLY"),
    ],
)
def test_limit_clause_per_dialect(dialect: str, expected: str) -> None:
    """Ограничение выборки соответствует диалекту."""
    assert limit_clause(dialect)[1] == expected


@pytest.mark.unit
def test_limit_clause_mssql_uses_top() -> None:
    """MSSQL использует ``TOP (...)`` (префикс, а не суффикс)."""
    prefix, suffix = limit_clause("mssql")
    assert prefix == "TOP (:limit)"
    assert suffix == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_uses_fetch_first_for_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling для Oracle не использует ``LIMIT``."""
    harness = _SqlHarness()
    sub = CDCSubscription(profile="oracle_1", tables=["orders"], interval=0)
    harness.sub = sub
    _install_registry(monkeypatch, harness, "oracle")

    await _PollingStrategy().run(sub, _noop_dispatch)

    assert harness.captured
    sql = harness.captured[0]
    assert "FETCH FIRST :limit ROWS ONLY" in sql
    assert "LIMIT :limit" not in sql


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_uses_top_for_mssql(monkeypatch: pytest.MonkeyPatch) -> None:
    """Polling для MSSQL использует ``TOP (:limit)``."""
    harness = _SqlHarness()
    sub = CDCSubscription(profile="mssql_1", tables=["orders"], interval=0)
    harness.sub = sub
    _install_registry(monkeypatch, harness, "mssql")

    await _PollingStrategy().run(sub, _noop_dispatch)

    assert harness.captured
    assert "SELECT TOP (:limit) * FROM orders" in harness.captured[0]


# ════════════════════════════════════════════════════════════════════
# 2. LogMiner — только Oracle + START_LOGMNR
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logminer_rejects_non_oracle_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LogMiner для не-Oracle СУБД — fail-fast с понятным сообщением."""
    harness = _SqlHarness()
    sub = CDCSubscription(
        profile="pg_1", tables=["orders"], strategy="logminer", interval=0
    )
    harness.sub = sub
    _install_registry(monkeypatch, harness, "postgresql")

    with pytest.raises(ValueError, match="requires an Oracle profile"):
        await _LogMinerStrategy().run(sub, _noop_dispatch)

    assert harness.captured == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logminer_calls_start_logmnr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Перед чтением ``V$LOGMNR_CONTENTS`` вызывается ``START_LOGMNR``."""
    harness = _SqlHarness()
    sub = CDCSubscription(
        profile="oracle_1", tables=["orders"], strategy="logminer", interval=0
    )
    harness.sub = sub
    _install_registry(monkeypatch, harness, "oracle")

    await _LogMinerStrategy().run(sub, _noop_dispatch)

    assert len(harness.captured) == 3
    assert "DBMS_LOGMNR.START_LOGMNR" in harness.captured[0]
    assert "V$LOGMNR_CONTENTS" in harness.captured[1]
    assert "DBMS_LOGMNR.END_LOGMNR" in harness.captured[2]
