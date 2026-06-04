"""Unit-тесты SQLAlchemyRepository.

Покрывают CRUD, list, filter, pagination, count, first_or_last,
а также NotFoundError при отсутствии записи.

Примечание: в текущей реализации ``SQLAlchemyRepository`` отсутствуют
методы ``exists``, ``bulk_create``, ``bulk_update`` — они не включены
в тестовый набор.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi_pagination import Params
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, configure_mappers, mapped_column

pytest.importorskip("aiosqlite")

from src.backend.core.errors import NotFoundError
from src.backend.infrastructure.database.models.base import BaseModel
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.repositories.base import SQLAlchemyRepository


class _TestItem(BaseModel):
    """Минимальная тестовая модель для проверки базового репозитория."""

    __tablename__ = "test_items"
    name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[int | None] = mapped_column(default=None)


# Конфигурируем mappers до создания таблиц, чтобы sqlalchemy_continuum
# создал вспомогательные таблицы (transaction, activity, ...).
configure_mappers()

_TEST_TABLES = [
    BaseModel.metadata.tables["test_items"],
    BaseModel.metadata.tables["test_items_version"],
    BaseModel.metadata.tables["transaction"],
    BaseModel.metadata.tables["activity"],
]


@pytest_asyncio.fixture
async def repo() -> AsyncIterator[SQLAlchemyRepository[_TestItem]]:
    """In-memory SQLite + SQLAlchemyRepository с подменённым session_maker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=_TEST_TABLES
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    original_sm = main_session_manager.session_maker
    main_session_manager.session_maker = factory

    try:
        yield SQLAlchemyRepository(_TestItem)
    finally:
        main_session_manager.session_maker = original_sm
        await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_creates_record(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``add`` создаёт запись и возвращает объект с проставленным id."""
    obj = await repo.add(data={"name": "alpha", "value": 1})

    assert obj.id is not None
    assert obj.name == "alpha"
    assert obj.value == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_by_key_value(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``get`` по ключу/значению возвращает единичный объект."""
    created = await repo.add(data={"name": "beta", "value": 2})

    found = await repo.get(key="id", value=created.id)

    assert isinstance(found, _TestItem)
    assert found.id == created.id
    assert found.name == "beta"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_not_found_returns_empty_dict(
    repo: SQLAlchemyRepository[_TestItem],
) -> None:
    """При отсутствии записи ``get`` возвращает пустой dict (не None)."""
    result = await repo.get(key="id", value=999999)

    assert result == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_returns_all_records(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``get`` без фильтров возвращает список всех записей."""
    await repo.add(data={"name": "a", "value": 1})
    await repo.add(data={"name": "b", "value": 2})

    items = await repo.get()

    assert isinstance(items, list)
    assert len(items) == 2
    assert {it.name for it in items} == {"a", "b"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_paginated(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``get`` с ``pagination`` возвращает словарь с items и total."""
    for i in range(5):
        await repo.add(data={"name": f"item-{i}", "value": i})

    result = await repo.get(pagination=Params(page=1, size=2))

    assert isinstance(result, dict)
    assert "items" in result
    assert "total" in result
    assert len(result["items"]) == 2
    assert result["total"] == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``count`` возвращает число записей в таблице."""
    assert await repo.count() == 0

    await repo.add(data={"name": "one"})
    await repo.add(data={"name": "two"})

    assert await repo.count() == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``update`` изменяет указанные поля и возвращает обновлённый объект."""
    created = await repo.add(data={"name": "old", "value": 10})

    updated = await repo.update(
        key="id", value=created.id, data={"name": "new", "value": 20}
    )

    assert updated.name == "new"
    assert updated.value == 20
    assert updated.id == created.id

    # Проверяем персистентность
    fetched = await repo.get(key="id", value=created.id)
    assert isinstance(fetched, _TestItem)
    assert fetched.name == "new"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_not_found_raises(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``update`` по несуществующему id выбрасывает NotFoundError."""
    with pytest.raises(NotFoundError):
        await repo.update(key="id", value=999999, data={"name": "ghost"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``delete`` удаляет запись по ключу/значению."""
    created = await repo.add(data={"name": "to-delete"})
    assert await repo.count() == 1

    await repo.delete(key="id", value=created.id)

    assert await repo.count() == 0
    assert await repo.get(key="id", value=created.id) == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_first_or_last_asc(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``first_or_last`` с order='asc' возвращает первые N записей."""
    for i in range(3):
        await repo.add(data={"name": f"item-{i}"})

    result = await repo.first_or_last(limit=2, by="id", order="asc")

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].id < result[1].id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_first_or_last_desc(repo: SQLAlchemyRepository[_TestItem]) -> None:
    """``first_or_last`` с order='desc' возвращает последние N записей."""
    for i in range(3):
        await repo.add(data={"name": f"item-{i}"})

    result = await repo.first_or_last(limit=2, by="id", order="desc")

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].id > result[1].id
