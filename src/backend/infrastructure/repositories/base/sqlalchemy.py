from __future__ import annotations

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
from src.backend.infrastructure.repositories.base.base import (
    AbstractRepository,  # S64 W2: cross-import
)


class SQLAlchemyRepository[ConcreteTable: BaseModel](AbstractRepository[ConcreteTable]):
    """
    Базовый класс для взаимодействия с БД с использованием SQLAlchemy.
    Реализует методы для работы с конкретной моделью таблицы.
    """

    class HelperMethods:
        """
        Вспомогательные методы для работы с базой данных.
        """

        def __init__(
            self,
            model: type[ConcreteTable],  # type: ignore
            main_class: type[AbstractRepository],
            load_joined_models: bool = False,
        ):
            self.model = model
            self.load_joined_models = load_joined_models
            self.main_class = main_class

        async def _prepare_and_save_object(
            self,
            session: AsyncSession,
            data: list[dict[str, Any]],
            existing_object: ConcreteTable | None = None,  # type: ignore
            ignore_none: bool = True,
            load_into_memory: bool = True,
        ) -> ConcreteTable:  # type: ignore
            """
            Обрабатывает данные и сохраняет объект в базе данных.
            """
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
            query_or_object: Select | ConcreteTable,  # type: ignore
            is_return_list: bool = False,
        ) -> ConcreteTable | None | list[ConcreteTable]:  # type: ignore
            """
            Выполняет запрос или подгружает связи для объекта.

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
                    objects: list[ConcreteTable] = (  # type: ignore
                        result.scalars().unique().all()
                    )
                    return objects if objects else []
                # Возвращаем один объект
                obj: ConcreteTable | None = result.scalars().first()  # type: ignore
                return obj

            if self.load_joined_models:
                # Если объект не в сессии, добавляем его
                if query_or_object not in session:
                    session.add(query_or_object)

                # Обновляем объект и подгружаем связи
                await session.flush()
                await session.refresh(instance=query_or_object)

            return query_or_object

        def _get_selectinload_options(self) -> list:
            """
            Формирует список опций для загрузки связанных моделей.
            """
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
        ) -> ConcreteTable | None:  # type: ignore
            """
            Выполняет SQL-запрос (INSERT или UPDATE) и возвращает созданный или обновленный объект.
            """
            await session.flush()
            result = await session.execute(stmt)
            if not result:
                raise DatabaseError(message="Failed to create/update record")

            primary_key = result.unique().scalar_one_or_none().id
            query = select(self.model).where(self.model.id == primary_key)
            return await self._get_loaded_object(session, query)

        async def _get_versions_query(
            self,
            session: AsyncSession,
            object_id: int,
            order: str = "asc",
            limit: int | None = None,
        ) -> Sequence[ConcreteTable]:  # type: ignore
            """
            Общий метод для получения версий объекта.
            """
            obj = await self.main_class.get(session=session, key="id", value=object_id)

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

    def __init__(
        self, model: type[ConcreteTable] = None, load_joined_models: bool = False
    ):
        self.model = model
        self.load_joined_models = load_joined_models
        self.helper = self.HelperMethods(
            model=model, load_joined_models=load_joined_models, main_class=self
        )

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
        """
        Получить объект по ключу и значению или по фильтру.

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

        order_by = asc(by) if order == "asc" else desc(by)

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
        """
        Получить список объектов с пагинацией.

        :param session: Асинхронная сессия SQLAlchemy.
        :param filter: Фильтр для запроса (опционально).
        :param pagination: Параметры пагинации (опционально).
        :param by: Поле для сортировки.
        :param order: Порядок сортировки ("asc" или "desc").
        :return: Словарь с items и total.
        """
        order_by = asc(by) if order == "asc" else desc(by)

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
        """
        Получить количество объектов в таблице.

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
        """
        Получить первый/-е или последний/-е объект в таблице, отсортированный по указанному полю.

        :param session: Асинхронная сессия SQLAlchemy.
        :param by: Поле для сортировки.
        :param order: Порядок сортировки ("asc" или "desc").
        :param limit: Количество записей.
        :return: Первый или последний объект.
        """
        order_by = (
            asc(by) if order == "asc" else desc(by)
        )  # Определяем порядок сортировки

        query = select(self.model).order_by(order_by).limit(limit)  # Создаем запрос
        return await self.helper._get_loaded_object(  # type: ignore
            session=session, query_or_object=query, is_return_list=True
        )

    @main_session_manager.connection()
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавить новый объект в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        """
        return await self.helper._prepare_and_save_object(session=session, data=data)

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
        """
        Обновить объект в таблице.

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
    async def delete(
        self, session: AsyncSession, key: str, value: Any
    ) -> int | None:
        """
        Удалить объект из таблицы по ключу и значению.

        S83 W2 (V2 P0 N1): возвращает ID удалённого объекта (или None),
        чтобы caller мог залогировать audit event. Раньше возвращал None
        → audit терял информацию что именно удалено.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска.
        :return: ID удалённого объекта или None если не найден.
        """
        result = await session.execute(
            delete(self.model)
            .where(getattr(self.model, key) == value)
            .returning(self.model.id)
        )
        await session.flush()
        row = result.scalar_one_or_none()
        return int(row) if row is not None else None

    @main_session_manager.connection(commit=False)
    async def get_all_versions(
        self, session: AsyncSession, object_id: int, order: str
    ) -> Sequence[Any]:
        """
        Получить все версии объекта.
        """
        return await self.helper._get_versions_query(
            session=session, object_id=object_id, order=order
        )

    @main_session_manager.connection(commit=False)
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> dict[str, Any] | None:
        """
        Получить последнюю версию объекта.
        """
        versions = await self.helper._get_versions_query(
            session=session, object_id=object_id, order="desc", limit=1
        )
        return versions[0] if versions else None

    @main_session_manager.connection()
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> dict[str, Any]:
        """
        Восстановить объект до указанной версии и вернуть информацию о транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Информация о восстановленной версии.
        """
        version_model = version_class(self.model)  # Получаем модель версий
        target_version = await session.execute(
            select(version_model).filter(
                version_model.id == object_id,
                version_model.transaction_id == transaction_id,
            )
        )
        target_version = target_version.scalars().first()

        if not target_version:
            raise NotFoundError(
                message=f"Version with transaction_id={transaction_id} not found"
            )

        # Преобразуем версию в словарь данных для обновления
        update_data = {
            attr: getattr(target_version, attr)
            for attr in target_version.__table__.columns.keys()  # type: ignore
        }

        return await self.update(
            key="id",
            value=object_id,
            data=update_data,
            ignore_none=False,  # Не игнорируем пустые значения при восстановлении
        )
