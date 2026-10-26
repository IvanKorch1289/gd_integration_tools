"""Минимальные протоколы для репозиториев.

Wave 6.2: создано для устранения layer-violations в services/core/*,
которые ранее напрямую импортировали `infrastructure.repositories.*`.

Цель: services-слой должен зависеть только от Protocol, конкретные
SQLAlchemy-репозитории остаются в infrastructure/.

Каждый Protocol специфичен для своего репозитория, но все они
наследуют общие CRUD-операции через :class:`RepositoryProtocol`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = (
    "FileRepositoryProtocol",
    "OrderKindRepositoryProtocol",
    "OrderRepositoryProtocol",
    "RepositoryProtocol",
    "UserRepositoryProtocol",
)


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Минимальный CRUD-контракт SQLAlchemy-репозитория.

    Точная сигнатура методов наследуется из
    ``infrastructure.repositories.base.AbstractRepository`` —
    Protocol описывает только публичную поверхность, которая нужна
    сервисам.
    """

    async def add(self, *args: Any, **kwargs: Any) -> Any:
        """Добавить новую сущность в repository (INSERT)."""
        ...

    async def update(self, *args: Any, **kwargs: Any) -> Any:
        """Обновить существующую сущность (UPDATE)."""
        ...

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        """Получить одну сущность по primary key; None если не найдено."""
        ...

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        """Удалить сущность по primary key."""
        ...

    async def first_or_last(self, *args: Any, **kwargs: Any) -> Any:
        """Получить первую/последнюю запись (сортировка по PK)."""
        ...

    async def get_paginated(self, *args: Any, **kwargs: Any) -> Any:
        """Получить страницу записей с пагинацией.

        Cycle 172 (Wave 4.1): метод отсутствовал в протоколе, хотя
        ``services/core/base/crud_mixin.py`` вызывает
        ``self.repo.get_paginated(...)`` — сервисный слой зависел от
        недекларированной поверхности.
        """
        ...

    async def count(self, *args: Any, **kwargs: Any) -> Any:
        """Получить количество записей в таблице.

        Cycle 172 (Wave 4.1): отсутствовал в протоколе, хотя
        реализация ``SQLAlchemyRepository.count`` существует и является
        частью публичной поверхности репозитория.
        """
        ...

    async def bulk_create(self, *args: Any, **kwargs: Any) -> Any:
        """Массово вставить записи одним INSERT.

        Cycle 172 (Wave 4.1): отсутствовал в протоколе, хотя
        ``SQLAlchemyRepository.bulk_create`` реализован.
        """
        ...

    async def get_all_versions(self, *args: Any, **kwargs: Any) -> Any:
        """Получить все версии сущности (versioning pattern)."""
        ...

    async def get_latest_version(self, *args: Any, **kwargs: Any) -> Any:
        """Получить последнюю версию сущности."""
        ...

    async def restore_to_version(self, *args: Any, **kwargs: Any) -> Any:
        """Восстановить сущность к указанной версии."""
        ...


@runtime_checkable
class OrderRepositoryProtocol(RepositoryProtocol, Protocol):
    """Контракт репозитория заказов."""


@runtime_checkable
class OrderKindRepositoryProtocol(RepositoryProtocol, Protocol):
    """Контракт репозитория видов заказов."""


@runtime_checkable
class FileRepositoryProtocol(RepositoryProtocol, Protocol):
    """Контракт репозитория файлов."""

    async def add_link(self, *args: Any, **kwargs: Any) -> Any:
        """Связь файла с заказом (или иной сущностью)."""
        ...


@runtime_checkable
class UserRepositoryProtocol(RepositoryProtocol, Protocol):
    """Контракт репозитория пользователей."""

    async def get_by_username(self, *args: Any, **kwargs: Any) -> Any:
        """Поиск пользователя по логину."""
        ...
