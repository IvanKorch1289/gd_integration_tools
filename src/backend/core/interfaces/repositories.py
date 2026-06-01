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
    "RepositoryProtocol",
    "OrderRepositoryProtocol",
    "OrderKindRepositoryProtocol",
    "FileRepositoryProtocol",
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

    async def add(self, *args: Any, **kwargs: Any) -> Any: ...
    async def update(self, *args: Any, **kwargs: Any) -> Any: ...
    async def get(self, *args: Any, **kwargs: Any) -> Any: ...
    async def delete(self, *args: Any, **kwargs: Any) -> Any: ...
    async def first_or_last(self, *args: Any, **kwargs: Any) -> Any: ...
    async def get_all_versions(self, *args: Any, **kwargs: Any) -> Any: ...
    async def get_latest_version(self, *args: Any, **kwargs: Any) -> Any: ...
    async def restore_to_version(self, *args: Any, **kwargs: Any) -> Any: ...


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
