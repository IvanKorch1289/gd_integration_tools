"""Абстрактный контракт репозитория.

Cycle 172 (Wave 4.4): сигнатуры абстрактных методов **согласованы** с
реализацией ``SQLAlchemyRepository``, чтобы убрать ``# type: ignore[override]``
из десяти методов.

Что изменилось по существу (все изменения — расширение контракта, обратная
совместимость сохранена):

* ``get`` — ``key``/``value`` стали необязательными, добавлены ``filter`` /
  ``pagination`` / ``by`` / ``order``; возвращаемый тип widened до фактического
  (объект | список | словарь | None).
* ``first_or_last`` — добавлен ``limit`` (первым позиционным, как в реализации)
  и возвращаемый тип — список.
* ``delete`` — возвращает ``int | None`` (ID удалённой записи для audit).
* ``get_all_versions`` — добавлен ``order`` по умолчанию.
* ``get_latest_version`` / ``restore_to_version`` — возвращаемый тип
  ``ConcreteTable | None`` / ``ConcreteTable``: реализация возвращала объект
  модели, но была размечена как ``dict[str, Any]`` — это была неточность
  аннотации, а не поведение.

Ни один существующий вызывающий код не затронут: все они используют
именованные аргументы.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Params
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.domain.models.base import BaseModel

__all__ = ("AbstractRepository",)


class AbstractRepository[ConcreteTable: BaseModel](ABC):
    """Абстрактный базовый класс для репозиториев.

    Определяет интерфейс для работы с базой данных.
    """

    @abstractmethod
    async def get(
        self,
        session: AsyncSession,
        key: str | None = None,
        value: Any = None,
        filter: Filter | None = None,
        pagination: Params | None = None,
        by: str | None = "id",
        order: str = "asc",
    ) -> ConcreteTable | list[ConcreteTable] | dict[str, Any] | None:
        """Получить объект по ключу и значению или по фильтру."""
        raise NotImplementedError

    @abstractmethod
    async def count(self, session: AsyncSession) -> int:
        """Получить количество объектов в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def first_or_last(
        self, session: AsyncSession, limit: int = 1, by: str = "id", order: str = "asc"
    ) -> list[ConcreteTable]:
        """Получить первую/последнюю запись, отсортированную по указанному полю."""
        raise NotImplementedError

    @abstractmethod
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """Добавить новый объект в таблицу."""
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        data: dict[str, Any],
        ignore_none: bool = True,
        load_into_memory: bool = False,
    ) -> ConcreteTable:
        """Обновить объект в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def delete(
        self, session: AsyncSession, key: str, value: Any
    ) -> int | None:
        """Удалить объект из таблицы по ключу и значению.

        Возвращает ID удалённого объекта (или ``None``), чтобы вызывающий
        мог записать audit-событие.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_all_versions(
        self, session: AsyncSession, object_id: int, order: str = "asc"
    ) -> Sequence[Any]:
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
