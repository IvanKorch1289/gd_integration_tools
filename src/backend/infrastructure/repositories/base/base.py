from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Params
from sqlalchemy import (
    Insert,
    Result,
    Select,
    Update,
    asc,
    delete,
    desc,
    func,
    inspect,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_continuum import version_class

from src.backend.core.errors import DatabaseError, NotFoundError
from src.backend.infrastructure.database.models.base import BaseModel
from src.backend.infrastructure.database.session_manager import main_session_manager





class AbstractRepository[ConcreteTable: BaseModel](ABC):
    """
    Абстрактный базовый класс для репозиториев.
    Определяет интерфейс для работы с базой данных.
    """

    @abstractmethod
    async def get(self, session: AsyncSession, key: str, value: Any) -> ConcreteTable:
        """Получить объект по ключу и значению."""
        raise NotImplementedError

    @abstractmethod
    async def count(self, session: AsyncSession) -> int:
        """Получить количество объектов в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def first_or_last(
        self, session: AsyncSession, by: str = "id", order: str = "asc"
    ) -> ConcreteTable:
        """Получить первый или последний объект в таблице, отсортированный по указанному полю."""
        raise NotImplementedError

    @abstractmethod
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """Добавить новый объект в таблицу."""
        raise NotImplementedError

    @abstractmethod
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        """Обновить объект в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, session: AsyncSession, key: str, value: Any) -> None:
        """Удалить объект из таблицы по ключу и значению."""
        raise NotImplementedError

    @abstractmethod
    async def get_all_versions(
        self, session: AsyncSession, object_id: int
    ) -> list[ConcreteTable]:
        """Получить все версии объекта по его id."""
        raise NotImplementedError

    @abstractmethod
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> ConcreteTable | None:
        """Получить последнюю версию объекта."""
        raise NotImplementedError

    @abstractmethod
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> ConcreteTable:
        """Восстановить объект до указанной версии."""
        raise NotImplementedError
