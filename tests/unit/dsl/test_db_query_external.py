"""Wave 6.2 — smoke-тесты для ``ExternalDbQueryProcessor``.

Использует mock-провайдер ``get_external_session_manager_provider``, чтобы
не подниматься в реальную внешнюю БД. Проверяется:
* params собираются из правильного источника (body / properties / headers);
* SQL прокидывается в ``session.execute`` корректно;
* result_property записывается;
* commit вызывается, когда задано;
* round-trip ``to_spec()``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.db_query_external import ExternalDbQueryProcessor


def _ctx() -> ExecutionContext:
    return ExecutionContext()


def _make_session_mock(
    *, rows: list[dict[str, Any]] | None = None, scalar: Any = None
) -> tuple[MagicMock, AsyncMock]:
    """Создаёт mock-сессию SQLAlchemy с асинхронными методами execute/commit."""
    result = MagicMock()
    mappings = MagicMock()
    mappings.all.return_value = rows or []
    mappings.first.return_value = (rows or [None])[0]
    result.mappings.return_value = mappings
    result.scalar_one_or_none.return_value = scalar

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    session_manager = MagicMock()
    session_manager.create_session = MagicMock(return_value=session_cm)

    return session_manager, session


@pytest.fixture
def patch_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Подменяет провайдер session_manager на mock и возвращает session-mock."""
    holder: dict[str, Any] = {}

    def _install(rows=None, scalar=None) -> Any:
        manager, session = _make_session_mock(rows=rows, scalar=scalar)
        holder["session"] = session
        holder["manager"] = manager

        def _provider() -> Any:
            return lambda profile: manager

        monkeypatch.setattr(
            "src.core.di.providers.get_external_session_manager_provider",
            _provider,
        )
        return holder

    return _install


@pytest.mark.asyncio
async def test_db_query_external_fetch_all_from_body(patch_provider: Any) -> None:
    """fetch=all + params_from=body передаёт body как dict-параметры."""
    holder = patch_provider(rows=[{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}])

    proc = ExternalDbQueryProcessor(
        profile="oracle_prod",
        sql="SELECT * FROM users WHERE active = :active",
    )
    ex = Exchange(in_message=Message(body={"active": True}, headers={}))
    await proc.process(ex, _ctx())

    assert ex.out_message.body == [{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}]
    assert ex.properties["db_result"] == [
        {"id": 1, "name": "X"},
        {"id": 2, "name": "Y"},
    ]
    holder["session"].execute.assert_awaited_once()
    args, _ = holder["session"].execute.call_args
    # second arg — словарь параметров
    assert args[1] == {"active": True}
    holder["session"].commit.assert_not_called()


@pytest.mark.asyncio
async def test_db_query_external_fetch_one(patch_provider: Any) -> None:
    holder = patch_provider(rows=[{"id": 42}])
    proc = ExternalDbQueryProcessor(
        profile="oracle_prod",
        sql="SELECT id FROM users WHERE id = :id",
        fetch="one",
    )
    ex = Exchange(in_message=Message(body={"id": 42}, headers={}))
    await proc.process(ex, _ctx())
    assert ex.out_message.body == {"id": 42}
    holder["session"].execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_query_external_fetch_scalar(patch_provider: Any) -> None:
    patch_provider(rows=[], scalar=99)
    proc = ExternalDbQueryProcessor(
        profile="oracle_prod",
        sql="SELECT COUNT(*) FROM users",
        params_from="none",
        fetch="scalar",
    )
    ex = Exchange(in_message=Message(body=None, headers={}))
    await proc.process(ex, _ctx())
    assert ex.out_message.body == 99


@pytest.mark.asyncio
async def test_db_query_external_commit_on_write(patch_provider: Any) -> None:
    """commit=True → вызывается session.commit()."""
    holder = patch_provider(rows=[])
    proc = ExternalDbQueryProcessor(
        profile="oracle_prod",
        sql="UPDATE users SET active = :active WHERE id = :id",
        commit=True,
        fetch="scalar",
    )
    ex = Exchange(in_message=Message(body={"active": False, "id": 1}, headers={}))
    await proc.process(ex, _ctx())
    holder["session"].commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_query_external_params_from_properties(patch_provider: Any) -> None:
    holder = patch_provider(rows=[])
    proc = ExternalDbQueryProcessor(
        profile="oracle_prod",
        sql="SELECT 1",
        params_from="properties",
    )
    ex = Exchange(in_message=Message(body={}, headers={}))
    ex.properties["custom"] = "value"
    await proc.process(ex, _ctx())
    args, _ = holder["session"].execute.call_args
    assert args[1] == {"custom": "value"}


def test_db_query_external_to_spec_minimal() -> None:
    proc = ExternalDbQueryProcessor(profile="p1", sql="SELECT 1")
    spec = proc.to_spec()
    assert spec == {"db_query_external": {"profile": "p1", "sql": "SELECT 1"}}


def test_db_query_external_to_spec_full() -> None:
    proc = ExternalDbQueryProcessor(
        profile="p1",
        sql="SELECT 1",
        params_from="headers",
        result_property="custom",
        fetch="one",
        commit=True,
    )
    spec = proc.to_spec()
    assert spec == {
        "db_query_external": {
            "profile": "p1",
            "sql": "SELECT 1",
            "params_from": "headers",
            "result_property": "custom",
            "fetch": "one",
            "commit": True,
        }
    }


def test_db_query_external_validates_params_from() -> None:
    with pytest.raises(ValueError, match="params_from"):
        ExternalDbQueryProcessor(profile="p", sql="SELECT 1", params_from="invalid")


def test_db_query_external_validates_fetch() -> None:
    with pytest.raises(ValueError, match="fetch"):
        ExternalDbQueryProcessor(profile="p", sql="SELECT 1", fetch="invalid")
