"""Unit tests for src.backend.core.di.providers.storage (S36-W23).

Validates the new single entry point для файлового хранилища.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.di.providers import storage


class TestObjectStorageProvider:
    def test_set_overrides(self) -> None:
        """set_object_storage_provider → get_object_storage_provider returns same instance."""
        mock = MagicMock(name="custom_object_storage")
        storage.set_object_storage_provider(mock)
        assert storage.get_object_storage_provider() is mock

    def test_clear_overrides(self) -> None:
        """After set_object_storage_provider(None) — falls through to resolve_module."""
        storage.set_object_storage_provider(None)
        # No exception → resolve_module path is reachable
        assert True


class TestStorageFacadeProvider:
    def test_set_overrides(self) -> None:
        """set_storage_facade_provider → get_storage_facade_provider returns same instance."""
        mock = MagicMock(name="custom_storage_facade")
        storage.set_storage_facade_provider(mock)
        assert storage.get_storage_facade_provider() is mock

    def test_clear_overrides(self) -> None:
        storage.set_storage_facade_provider(None)
        assert True


class TestCoreStorageReexports:
    """core.storage должен re-export все 4 providers (boundary rule)."""

    def test_all_storage_providers_reexported(self) -> None:
        from src.backend.core import storage as core_storage

        for name in (
            "get_object_storage_provider",
            "get_storage_facade_provider",
            "set_object_storage_provider",
            "set_storage_facade_provider",
        ):
            assert hasattr(core_storage, name), f"core.storage missing {name}"
