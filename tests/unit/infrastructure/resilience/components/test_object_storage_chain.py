"""Tests for ``src.backend.infrastructure.resilience.components.object_storage_chain``.

W26.4: MinIO/S3 → LocalFS chain pattern. StorageGetCallable contract.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.resilience.components import (
    object_storage_chain as mod,
)
from src.backend.infrastructure.resilience.components.object_storage_chain import (
    StorageGetCallable,
    _local_fs_get,
    _primary_get,
    build_object_storage_fallbacks,
    build_object_storage_primary,
)


class TestStorageGetCallableType:
    """StorageGetCallable — Callable[[str], Awaitable[bytes]]."""

    def test_callable_annotation(self) -> None:
        assert StorageGetCallable is not None

    def test_callable_can_be_used_as_annotation(self) -> None:
        async def my_get(key: str) -> bytes:
            return key.encode("utf-8")

        assert callable(my_get)
        import asyncio

        result = asyncio.run(my_get("hello"))
        assert result == b"hello"


class TestPrimaryGet:
    """_primary_get() — primary storage (S3/MinIO/LocalFS fallback)."""

    @pytest.mark.asyncio
    async def test_calls_get_object_storage(self) -> None:
        mock_backend = MagicMock()
        mock_backend.download = AsyncMock(return_value=b"data")

        with patch(
            "src.backend.infrastructure.storage.factory.get_object_storage",
            return_value=mock_backend,
        ):
            result = await _primary_get("some/key.txt")

        assert result == b"data"
        mock_backend.download.assert_called_once_with("some/key.txt")

    @pytest.mark.asyncio
    async def test_propagates_key(self) -> None:
        mock_backend = MagicMock()
        mock_backend.download = AsyncMock(return_value=b"")

        with patch(
            "src.backend.infrastructure.storage.factory.get_object_storage",
            return_value=mock_backend,
        ):
            await _primary_get("my/special/path.json")

        mock_backend.download.assert_called_once_with("my/special/path.json")


class TestLocalFsGet:
    """_local_fs_get() — LocalFS fallback."""

    @pytest.mark.asyncio
    async def test_calls_get_local_fs_storage(self) -> None:
        mock_backend = MagicMock()
        mock_backend.download = AsyncMock(return_value=b"local_data")

        with patch(
            "src.backend.infrastructure.storage.factory.get_local_fs_storage",
            return_value=mock_backend,
        ):
            result = await _local_fs_get("local/key.txt")

        assert result == b"local_data"
        mock_backend.download.assert_called_once_with("local/key.txt")


class TestBuildObjectStoragePrimary:
    """build_object_storage_primary() — resolver."""

    def test_returns_callable(self) -> None:
        primary = build_object_storage_primary()
        assert callable(primary)

    def test_returns_actual_primary_get(self) -> None:
        primary = build_object_storage_primary()
        # Это _primary_get
        assert primary is _primary_get


class TestBuildObjectStorageFallbacks:
    """build_object_storage_fallbacks() — dict of fallbacks."""

    def test_returns_dict(self) -> None:
        fallbacks = build_object_storage_fallbacks()
        assert isinstance(fallbacks, dict)

    def test_contains_local_fs(self) -> None:
        fallbacks = build_object_storage_fallbacks()
        assert "local_fs" in fallbacks

    def test_local_fs_is_callable(self) -> None:
        fallbacks = build_object_storage_fallbacks()
        assert callable(fallbacks["local_fs"])

    def test_local_fs_is_local_fs_get(self) -> None:
        fallbacks = build_object_storage_fallbacks()
        assert fallbacks["local_fs"] is _local_fs_get


class TestAllExports:
    """__all__ проверка."""

    def test_exports_three_symbols(self) -> None:
        assert "StorageGetCallable" in mod.__all__
        assert "build_object_storage_primary" in mod.__all__
        assert "build_object_storage_fallbacks" in mod.__all__
        assert len(mod.__all__) == 3

    def test_functions_callable(self) -> None:
        assert callable(build_object_storage_primary)
        assert callable(build_object_storage_fallbacks)


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.infrastructure.resilience.components import (
            object_storage_chain as m,
        )

        assert m is mod

    def test_private_functions_have_underscore_prefix(self) -> None:
        # _primary_get, _local_fs_get — private (не в __all__)
        assert hasattr(mod, "_primary_get")
        assert hasattr(mod, "_local_fs_get")
        assert "_primary_get" not in mod.__all__
        assert "_local_fs_get" not in mod.__all__


class TestCallablesAsAsync:
    """Проверка что возвращаемые callables — async."""

    def test_primary_is_async_function(self) -> None:
        primary = build_object_storage_primary()
        assert inspect.iscoroutinefunction(primary)

    def test_local_fs_is_async_function(self) -> None:
        fallbacks = build_object_storage_fallbacks()
        assert inspect.iscoroutinefunction(fallbacks["local_fs"])


class TestStorageGetCallableSig:
    """StorageGetCallable signature."""

    def test_callable_signature(self) -> None:
        # Callable[[str], Awaitable[bytes]]
        async def fn(key: str) -> bytes:
            return b""

        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        assert params == ["key"]


class TestContractAsync:
    """StorageGetCallable contract: async, returns bytes."""

    @pytest.mark.asyncio
    async def test_real_callable_via_primary(self) -> None:
        # Полный цикл через primary
        mock_backend = MagicMock()
        mock_backend.download = AsyncMock(return_value=b"primary_bytes")

        with patch(
            "src.backend.infrastructure.storage.factory.get_object_storage",
            return_value=mock_backend,
        ):
            primary = build_object_storage_primary()
            result = await primary("key")

        assert result == b"primary_bytes"
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_real_callable_via_fallback(self) -> None:
        mock_backend = MagicMock()
        mock_backend.download = AsyncMock(return_value=b"local_bytes")

        with patch(
            "src.backend.infrastructure.storage.factory.get_local_fs_storage",
            return_value=mock_backend,
        ):
            fallbacks = build_object_storage_fallbacks()
            result = await fallbacks["local_fs"]("key")

        assert result == b"local_bytes"
        assert isinstance(result, bytes)