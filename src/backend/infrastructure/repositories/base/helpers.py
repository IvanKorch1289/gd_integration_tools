"""Вспомогательные методы репозитория SQLAlchemy.

Cycle 172 (MEDIUM-13): ``SQLAlchemyRepository`` был God-object'ом — 491 LOC
и 11 публичных методов (порог проекта: >300 строк, >10 методов). Класс
разбит на семейные модули; этот модуль содержит прежний вложенный класс
``HelperMethods``, вынесенный в отдельный модуль.

Публичное имя сохранено: ``SQLAlchemyRepository.HelperMethods`` остаётся
доступным (его наследует ``OrderRepository`` в
``extensions/core_entities/orders/repositories/orders.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import Insert, Result, Select, Update, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_continuum import version_class

from src.backend.core.domain.models.base import BaseModel
from src.backend.core.errors import DatabaseError

__all__ = ("RepositoryHelper",)


class RepositoryHelper[ConcreteTable: BaseModel]:
    """Вспомогательные методы для работы с базой данных.

    Раньше вложен в ``SQLAlchemyRepository`` как ``HelperMethods``. Само
    поведение не менялось — изменена только структура модуля.
    """

    def __init__(
        self,
        model: type[ConcreteTable],
        main_class: type[Any],
        load_joined_models: bool = False,
    ) -> None:
        self.model = model
        self.load_joined_models = load_joined_models
        self.main_class = main_class

    async def _prepare_and_save_object(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        existing_object: ConcreteTable | None = None,
        ignore_none: bool = True,
        load_into_memory: bool = True,
    ) -> ConcreteTable:
        """Обрабатывает данные и сохраняет объект в базе данных."""
        unsecret_data = await self.model.get_value_from_secret_str(data)

        if existing_object:
            for field, new_value in unsecret_data.items():
                if not ignore_none or new_value is not None:
                    setattr(existing_object, field, new_value)
            obj = existing_object
        else:
            obj = self.model(**unsecret_data)

        session.add(obj)
        await session.flush()

        if load_into_memory:
            # S83 W1 (V2 P0 N1): fix DetachedInstanceError.
            # session.refresh() marks all attrs as expired; после
            # @main_session_manager.connection() closes session
            # доступ к obj.field = DetachedInstanceError.
            # Решение: явно указываем attribute_names при refresh —
            # refresh() с конкретным списком не expire'ит остальные
            # attrs, и оставшиеся attrs остаются loaded после commit.
            # Это безопаснее чем expire_on_commit=False (глобально
            # для session) и не ломает concurrent sessions.
            mapper = inspect(obj.__class__)
            all_column_names = [c.key for c in mapper.columns]
            await session.refresh(instance=obj, attribute_names=all_column_names)

        return obj

    async def _get_loaded_object(
        self,
        session: AsyncSession,
        query_or_object: Select | ConcreteTable,
        is_return_list: bool = False,
    ) -> ConcreteTable | list[ConcreteTable] | None:
        """Выполняет запрос или подгружает связи для объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param query_or_object: Запрос или объект для загрузки.
        :param is_return_list: Если True, возвращает список объектов. Иначе — один объект или None.
        :return: Объект, список объектов или пустой список/словарь, если данные не найдены.
        """
        if isinstance(query_or_object, Select):
            # Выполняем запрос
            result: Result = await session.execute(query_or_object)

            if is_return_list:
                # Возвращаем список объектов
                objects = cast(
                    "list[ConcreteTable]", result.scalars().unique().all()
                )
                return objects or []
            # Возвращаем один объект
            obj: ConcreteTable | None = result.scalars().first()
            return obj

        if self.load_joined_models:
            # Если объект не в сессии, добавляем его
            if query_or_object not in session:
                session.add(query_or_object)

            # Обновляем объект и подгружаем связи
            await session.flush()
            await session.refresh(instance=query_or_object)

        return query_or_object

    def _get_selectinload_options(self) -> list[Any]:
        """Формирует список опций для загрузки связанных моделей."""
        from sqlalchemy.orm import selectinload

        mapper = inspect(self.model)
        relationships = [rel.key for rel in mapper.relationships]

        return [
            selectinload(getattr(self.model, key))
            for key in relationships
            if key not in getattr(self.model, "EXCLUDED_RELATIONSHIPS", set())
            and key != "versions"
        ]

    async def _execute_stmt(
        self, session: AsyncSession, stmt: Insert | Update
    ) -> ConcreteTable | None:
        """Выполняет SQL-запрос (INSERT или UPDATE) и возвращает созданный или обновленный объект."""
        await session.flush()
        result = await session.execute(stmt)
        if not result:
            raise DatabaseError(message="Failed to create/update record")

        primary_key = result.unique().scalar_one_or_none().id  # type: ignore[union-attr]  # R2.MYPY: scalar_one_or_none returns Row | None
        query = select(self.model).where(self.model.id == primary_key)
        loaded = await self._get_loaded_object(session, query)
        return cast("ConcreteTable | None", loaded)

    async def _get_versions_query(
        self,
        session: AsyncSession,
        object_id: int,
        order: str = "asc",
        limit: int | None = None,
    ) -> Sequence[ConcreteTable]:
        """Общий метод для получения версий объекта."""
        obj = await self.main_class.get(
            session=session, key="id", value=object_id
        )

        if not obj or (isinstance(obj, list) and not obj):
            return []

        version_model = version_class(self.model)
        query = select(version_model).filter(version_model.id == obj.id)

        if order == "asc":
            query = query.order_by(version_model.transaction_id)
        elif order == "desc":
            query = query.order_by(version_model.transaction_id.desc())

        if limit:
            query = query.limit(limit)

        result = await session.execute(query)

        return result.scalars().all()
