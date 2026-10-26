"""Versioning-миксин репозитория SQLAlchemy.

Cycle 172 (MEDIUM-13): ``SQLAlchemyRepository`` — God-object (491 LOC,
11 публичных методов). Вынесена versioning-часть; публичное имя класса
``SQLAlchemyRepository`` сохранено (см. ``sqlalchemy.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_continuum import version_class

from src.backend.core.domain.models.base import BaseModel
from src.backend.core.errors import NotFoundError
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.repositories.base.base import AbstractRepository
from src.backend.infrastructure.repositories.base.helpers import RepositoryHelper

__all__ = ("VersioningMixin",)


class VersioningMixin[ConcreteTable: BaseModel](AbstractRepository[ConcreteTable]):
    """Операции над версиями объекта (sqlalchemy-continuum).

    Наследует :class:`AbstractRepository` — см. комментарий в
    :class:`~src.backend.infrastructure.repositories.base.crud_mixin.CRUDMixin`.

    Требует от наследника атрибуты ``model`` и ``helper``.
    """

    model: type[ConcreteTable]
    helper: RepositoryHelper[ConcreteTable]

    @main_session_manager.connection(commit=False)
    async def get_all_versions(
        self, session: AsyncSession, object_id: int, order: str = "asc"
    ) -> Sequence[Any]:
        """Получить все версии объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param order: Порядок сортировки версий ("asc" или "desc").
        """
        return await self.helper._get_versions_query(
            session=session, object_id=object_id, order=order
        )

    @main_session_manager.connection(commit=False)
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> ConcreteTable | None:
        """Получить последнюю версию объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        """
        versions = await self.helper._get_versions_query(
            session=session, object_id=object_id, order="desc", limit=1
        )
        return versions[0] if versions else None

    @main_session_manager.connection()
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> ConcreteTable:
        """Восстановить объект до указанной версии и вернуть информацию о транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект.
        """
        version_model = version_class(self.model)  # Получаем модель версий
        target_version = await session.execute(
            select(version_model).filter(
                version_model.id == object_id,
                version_model.transaction_id == transaction_id,
            )
        )
        target_version = target_version.scalars().first()  # type: ignore[assignment]  # R2.MYPY: scalars().first() returns Any | None

        if not target_version:
            raise NotFoundError(
                message=f"Version with transaction_id={transaction_id} not found"
            )

        # Преобразуем версию в словарь данных для обновления
        update_data = {
            attr: getattr(target_version, attr)
            for attr in target_version.__table__.columns.keys()  # type: ignore
        }

        # ``update`` тоже декорирован ``connection()``. Сессия передаётся
        # явно, поэтому декоратор не открывает свою и не коммитит —
        # коммит делает внешний декоратор ``restore_to_version``.
        return await self.update(
            session=session,
            key="id",
            value=object_id,
            data=update_data,
            ignore_none=False,  # Не игнорируем пустые значения при восстановлении
        )
