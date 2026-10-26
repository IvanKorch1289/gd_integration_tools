"""CRUD-миксин репозитория SQLAlchemy.

Cycle 172 (MEDIUM-13): ``SQLAlchemyRepository`` — God-object (491 LOC,
11 публичных методов). Вынесена CRUD-часть; публичное имя класса
``SQLAlchemyRepository`` сохранено (см. ``sqlalchemy.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Params
from sqlalchemy import Result, asc, desc, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.domain.models.base import BaseModel
from src.backend.core.errors import NotFoundError
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.repositories.base.base import AbstractRepository
from src.backend.infrastructure.repositories.base.helpers import RepositoryHelper

__all__ = ("CRUDMixin",)


class CRUDMixin[ConcreteTable: BaseModel](AbstractRepository[ConcreteTable]):
    """Базовые CRUD-операции над моделью.

    Наследует :class:`AbstractRepository`, поэтому ``self`` в миксине
    совместим с абстрактным контрактом — иначе mypy счёл бы определения
    одного и того же метода в двух базовых классах несовместимыми.

    Требует от наследника атрибуты ``model`` и ``helper``.
    """

    model: type[ConcreteTable]
    helper: RepositoryHelper[ConcreteTable]

    @main_session_manager.connection(commit=False)
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
        """Получить объект по ключу и значению или по фильтру.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для фильтрации (опционально).
        :param value: Значение поля для фильтрации (опционально).
        :param filter: Фильтр для запроса (опционально).
        :param pagination: Параметры пагинации (опционально, deprecated — используйте ``get_paginated``).
        :return: Найденный объект, список объектов, словарь с пагинацией или None.
        """
        import warnings

        if pagination is not None:
            warnings.warn(
                "Passing pagination to get() is deprecated; use get_paginated() instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return await self.get_paginated(
                session=session,
                filter=filter,
                pagination=pagination,
                by=by,
                order=order,
            )

        is_return_list = False

        order_by: Any = asc(by) if order == "asc" else desc(by)  # type: ignore[arg-type,var-annotated]  # R2.MYPY: by: str|None → ColumnElement

        if filter:
            query = filter.filter(select(self.model).order_by(order_by))
            is_return_list = True
        elif key and value:
            query = (
                select(self.model)
                .where(getattr(self.model, key) == value)
                .order_by(order_by)
            )
        else:
            query = select(self.model).order_by(order_by)
            is_return_list = True

        return await self.helper._get_loaded_object(
            session=session, query_or_object=query, is_return_list=is_return_list
        )

    @main_session_manager.connection(commit=False)
    async def get_paginated(
        self,
        session: AsyncSession,
        filter: Filter | None = None,
        pagination: Params | None = None,
        by: str | None = "id",
        order: str = "asc",
    ) -> dict[str, Any]:
        """Получить список объектов с пагинацией.

        :param session: Асинхронная сессия SQLAlchemy.
        :param filter: Фильтр для запроса (опционально).
        :param pagination: Параметры пагинации (опционально).
        :param by: Поле для сортировки.
        :param order: Порядок сортировки ("asc" или "desc").
        :return: Словарь с items и total.
        """
        order_by: Any = asc(by) if order == "asc" else desc(by)  # type: ignore[arg-type,var-annotated]  # R2.MYPY: by: str|None → ColumnElement

        if filter:
            query = filter.filter(select(self.model).order_by(order_by))
        else:
            query = select(self.model).order_by(order_by)

        paginated_query = query
        if pagination:
            paginated_query = query.limit(pagination.size).offset(
                (pagination.page - 1) * pagination.size
            )

        items = await self.helper._get_loaded_object(
            session=session, query_or_object=paginated_query, is_return_list=True
        )

        # Считаем общее количество (оптимизированный запрос)
        count_query = query.with_only_columns(
            func.count(), maintain_column_froms=True
        ).order_by(None)
        total = await session.scalar(count_query)

        return {"items": items, "total": total}

    @main_session_manager.connection(commit=False)
    async def count(self, session: AsyncSession) -> int:
        """Получить количество объектов в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Количество объектов.
        """
        result: Result = await session.execute(func.count(self.model.id))
        count_value: int | None = result.scalar()

        if count_value is None:
            return 0  # Если результат None, возвращаем 0
        return count_value

    @main_session_manager.connection(commit=False)
    async def first_or_last(
        self, session: AsyncSession, limit: int = 1, by: str = "id", order: str = "asc"
    ) -> list[ConcreteTable]:
        """Получить первый/-е или последний/-е объект в таблице, отсортированный по указанному полю.

        :param session: Асинхронная сессия SQLAlchemy.
        :param by: Поле для сортировки.
        :param order: Порядок сортировки ("asc" или "desc").
        :param limit: Количество записей.
        :return: Первый или последний объект.
        """
        order_by: Any = (  # type: ignore[var-annotated]
            asc(by) if order == "asc" else desc(by)
        )  # Определяем порядок сортировки

        query = select(self.model).order_by(order_by).limit(limit)  # Создаем запрос
        return await self.helper._get_loaded_object(  # type: ignore[return-value]
            session=session, query_or_object=query, is_return_list=True
        )

    @main_session_manager.connection()
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """Добавить новый объект в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        """
        return await self.helper._prepare_and_save_object(session=session, data=data)

    @main_session_manager.connection()
    async def bulk_create(
        self,
        session: AsyncSession,
        model: type[ConcreteTable],
        data: list[dict[str, Any]],
    ) -> int:
        """
        Массово вставить строки через SQLAlchemy 2.0 ``session.execute(insert(model), data)``.

        Выполняет один ``INSERT INTO model ... VALUES (...), (...), (...)``
        в одной транзакции (без per-row commit). Для пустого ``data``
        возвращает ``0`` без обращения к БД.

        :param session: Асинхронная сессия SQLAlchemy.
        :param model: Класс ORM-модели, в которую выполняется вставка.
        :param data: Список словарей с данными строк (по одному на строку).
        :return: Количество вставленных строк (``len(data)``).
        """
        if not data:
            return 0

        unsecret_data: list[dict[str, Any]] = [
            await model.get_value_from_secret_str(item) for item in data
        ]

        await session.execute(insert(model), unsecret_data)
        await session.flush()

        return len(unsecret_data)

    @main_session_manager.connection()
    async def update(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        data: dict[str, Any],
        ignore_none: bool = True,  # По умолчанию игнорируем пустые значения
        load_into_memory: bool = False,  # По умолчанию объект загружается в память. False - если не требуется выводить измененные данные
    ) -> ConcreteTable:
        """Обновить объект в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска объекта.
        :param data: Данные для обновления объекта.
        :param ignore_none: Игнорировать пустые значения (True) или нет (False).
        :return: Обновленный объект.
        """
        query = select(self.model).where(getattr(self.model, key) == value)
        result = await session.execute(query)
        existing_object = result.scalar_one_or_none()
        if not existing_object:
            raise NotFoundError(message="Object not found")

        return await self.helper._prepare_and_save_object(
            session=session,
            data=data,
            existing_object=existing_object,
            ignore_none=ignore_none,
            load_into_memory=load_into_memory,
        )

    @main_session_manager.connection()
    async def delete(self, session: AsyncSession, key: str, value: Any) -> int | None:
        """Удалить объект из таблицы по ключу и значению.

        S83 W2 (V2 P0 N1): возвращает ID удалённого объекта (или None),
        чтобы caller мог залогировать audit event. Раньше возвращал None
        → audit терял информацию что именно удалено.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска.
        :return: ID удалённого объекта или None если не найден.
        """
        from sqlalchemy import delete

        result = await session.execute(
            delete(self.model)
            .where(getattr(self.model, key) == value)
            .returning(self.model.id)
        )
        await session.flush()
        row = result.scalar_one_or_none()
        return int(row) if row is not None else None
