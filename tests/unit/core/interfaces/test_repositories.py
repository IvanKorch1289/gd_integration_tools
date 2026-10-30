"""Unit tests for src.backend.core.interfaces.repositories.

Fake-реализации ниже повторяют **полную** публичную поверхность
``RepositoryProtocol`` (11 async-методов). Список методов в ``_FakeRepository``
должен совпадать с ``RepositoryProtocol.__protocol_attrs__`` — иначе
``isinstance`` начинает молча возвращать ``False`` (cycle 172 расширил
протокол методами ``get_paginated`` / ``count`` / ``bulk_create``, а Fake
остался от старой версии).
"""

from __future__ import annotations

from src.backend.core.interfaces.repositories import (
    FileRepositoryProtocol,
    OrderKindRepositoryProtocol,
    OrderRepositoryProtocol,
    RepositoryProtocol,
    UserRepositoryProtocol,
)


class _FakeRepository:
    """Минимальная реализация ``RepositoryProtocol`` (все async-методы)."""

    async def add(self, *args: object, **kwargs: object) -> object:
        return None

    async def update(self, *args: object, **kwargs: object) -> object:
        return None

    async def get(self, *args: object, **kwargs: object) -> object:
        return None

    async def delete(self, *args: object, **kwargs: object) -> object:
        return None

    async def first_or_last(self, *args: object, **kwargs: object) -> object:
        return None

    async def get_paginated(self, *args: object, **kwargs: object) -> object:
        return None

    async def count(self, *args: object, **kwargs: object) -> object:
        return None

    async def bulk_create(self, *args: object, **kwargs: object) -> object:
        return None

    async def get_all_versions(self, *args: object, **kwargs: object) -> object:
        return None

    async def get_latest_version(self, *args: object, **kwargs: object) -> object:
        return None

    async def restore_to_version(self, *args: object, **kwargs: object) -> object:
        return None


class _FakeFileRepository(_FakeRepository):
    """``_FakeRepository`` + ``add_link`` (контракт файлового репозитория)."""

    async def add_link(self, *args: object, **kwargs: object) -> object:
        return None


class _FakeUserRepository(_FakeRepository):
    """``_FakeRepository`` + ``get_by_username`` (контракт user-репозитория)."""

    async def get_by_username(self, *args: object, **kwargs: object) -> object:
        return None


class TestRepositoryProtocol:
    def test_is_runtime_checkable(self) -> None:
        assert isinstance(_FakeRepository(), RepositoryProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), RepositoryProtocol)

    def test_partial_implementation_fails(self) -> None:
        """Реализация без одного метода протокола не проходит isinstance.

        Страхует от «тихого» рассинхрона: если в протокол добавят метод,
        а Fake-реализация останется прежней — тест упадёт, а не начнёт
        возвращать ``False`` без видимой причины.
        """

        class MissingCount(_FakeRepository):
            count = None  # type: ignore[assignment]

        assert not isinstance(MissingCount(), RepositoryProtocol)


class TestSpecializedProtocols:
    def test_order_repo(self) -> None:
        assert isinstance(_FakeRepository(), OrderRepositoryProtocol)
        assert isinstance(_FakeRepository(), OrderKindRepositoryProtocol)

    def test_file_repo(self) -> None:
        assert isinstance(_FakeFileRepository(), FileRepositoryProtocol)

    def test_user_repo(self) -> None:
        assert isinstance(_FakeUserRepository(), UserRepositoryProtocol)
