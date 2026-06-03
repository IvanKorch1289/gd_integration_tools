"""Unit tests for src.backend.core.interfaces.repositories."""

from __future__ import annotations

from src.backend.core.interfaces.repositories import (
    FileRepositoryProtocol,
    OrderKindRepositoryProtocol,
    OrderRepositoryProtocol,
    RepositoryProtocol,
    UserRepositoryProtocol,
)


class TestRepositoryProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
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

            async def get_all_versions(self, *args: object, **kwargs: object) -> object:
                return None

            async def get_latest_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def restore_to_version(self, *args: object, **kwargs: object) -> object:
                return None

        assert isinstance(Fake(), RepositoryProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), RepositoryProtocol)


class TestSpecializedProtocols:
    def test_order_repo(self) -> None:
        class Fake:
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

            async def get_all_versions(self, *args: object, **kwargs: object) -> object:
                return None

            async def get_latest_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def restore_to_version(self, *args: object, **kwargs: object) -> object:
                return None

        assert isinstance(Fake(), OrderRepositoryProtocol)
        assert isinstance(Fake(), OrderKindRepositoryProtocol)

    def test_file_repo(self) -> None:
        class Fake:
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

            async def get_all_versions(self, *args: object, **kwargs: object) -> object:
                return None

            async def get_latest_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def restore_to_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def add_link(self, *args: object, **kwargs: object) -> object:
                return None

        assert isinstance(Fake(), FileRepositoryProtocol)

    def test_user_repo(self) -> None:
        class Fake:
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

            async def get_all_versions(self, *args: object, **kwargs: object) -> object:
                return None

            async def get_latest_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def restore_to_version(self, *args: object, **kwargs: object) -> object:
                return None

            async def get_by_username(self, *args: object, **kwargs: object) -> object:
                return None

        assert isinstance(Fake(), UserRepositoryProtocol)
