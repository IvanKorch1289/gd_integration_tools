"""Unit tests for infrastructure.decorators.caching.__init__."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.backend.infrastructure.decorators.caching as caching_mod
from src.backend.infrastructure.decorators.caching import (
    CachingDecorator,
    close_caches,
    existence_cache_key,
    get_existence_cache,
    get_metadata_cache,
    get_response_cache,
    metadata_cache_key,
    response_cache_key,
)


@pytest.fixture(autouse=True)
def _clear_cache_getters() -> None:
    """Clear lru_cache singletons between tests."""
    get_response_cache.cache_clear()
    get_metadata_cache.cache_clear()
    get_existence_cache.cache_clear()


@pytest.mark.unit
def test_imports() -> None:
    assert callable(close_caches)
    assert callable(get_response_cache)
    assert callable(get_metadata_cache)
    assert callable(get_existence_cache)
    assert callable(response_cache_key)
    assert callable(metadata_cache_key)
    assert callable(existence_cache_key)
    assert issubclass(CachingDecorator, object)


@pytest.mark.unit
def test_stable_hash_deterministic() -> None:
    from src.backend.infrastructure.decorators.caching import _stable_hash

    payload: dict[str, Any] = {"a": 1, "b": "two"}
    h1 = _stable_hash(payload)
    h2 = _stable_hash(payload)
    assert isinstance(h1, str)
    assert len(h1) == 64
    assert h1 == h2


@pytest.mark.unit
def test_response_cache_key_with_self() -> None:
    class Owner:
        pass

    async def func(self: Any, x: int) -> None: ...

    owner = Owner()
    key = response_cache_key(func, (owner, 1), {"y": 2})
    assert key.startswith("cache:Owner:func:")


@pytest.mark.unit
def test_response_cache_key_without_self() -> None:
    async def func(x: int) -> None: ...

    key = response_cache_key(func, (), {"y": 2})
    assert key.startswith(f"cache:{func.__module__}:func:")


@pytest.mark.unit
def test_metadata_cache_key_from_kwargs() -> None:
    async def func(key: str) -> None: ...

    assert metadata_cache_key(func, (), {"key": "my_key"}) == "s3:metadata:my_key"


@pytest.mark.unit
def test_metadata_cache_key_from_args() -> None:
    async def func(_: Any, key: str) -> None: ...

    assert metadata_cache_key(func, (None, "arg_key"), {}) == "s3:metadata:arg_key"


@pytest.mark.unit
def test_metadata_cache_key_fallback() -> None:
    async def func() -> None: ...

    assert metadata_cache_key(func, (), {}) == "s3:metadata:"


@pytest.mark.unit
def test_existence_cache_key_from_kwargs() -> None:
    async def func(key: str) -> None: ...

    assert existence_cache_key(func, (), {"key": "my_key"}) == "s3:exists:my_key"


@pytest.mark.unit
def test_existence_cache_key_from_args() -> None:
    async def func(_: Any, key: str) -> None: ...

    assert existence_cache_key(func, (None, "arg_key"), {}) == "s3:exists:arg_key"


@pytest.mark.unit
def test_existence_cache_key_fallback() -> None:
    async def func() -> None: ...

    assert existence_cache_key(func, (), {}) == "s3:exists:"


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_get_response_cache(mock_cd: MagicMock) -> None:
    instance = mock_cd.return_value
    cache = caching_mod.get_response_cache()
    assert cache is instance
    mock_cd.assert_called_once()
    call_kwargs = mock_cd.call_args.kwargs
    assert call_kwargs["key_prefix"] == "cache"
    assert call_kwargs["expire"] == 1800
    assert call_kwargs["use_memory_fallback"] is True
    assert call_kwargs["memory_max_size"] == 2048
    assert call_kwargs["use_disk_fallback"] is True
    assert call_kwargs["disk_directory"] == ".cache/external-requests"


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_get_metadata_cache(mock_cd: MagicMock) -> None:
    instance = mock_cd.return_value
    cache = caching_mod.get_metadata_cache()
    assert cache is instance
    call_kwargs = mock_cd.call_args.kwargs
    assert call_kwargs["key_prefix"] == "s3:metadata"
    assert call_kwargs["expire"] == 300
    assert call_kwargs["renew_ttl"] is True
    assert call_kwargs["use_disk_fallback"] is False


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_get_existence_cache(mock_cd: MagicMock) -> None:
    instance = mock_cd.return_value
    cache = caching_mod.get_existence_cache()
    assert cache is instance
    call_kwargs = mock_cd.call_args.kwargs
    assert call_kwargs["key_prefix"] == "s3:exists"
    assert call_kwargs["expire"] == 60
    assert call_kwargs["use_disk_fallback"] is False


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_getattr_response_cache(mock_cd: MagicMock) -> None:
    caching_mod.get_response_cache.cache_clear()
    instance = mock_cd.return_value
    cache = caching_mod.response_cache
    assert cache is instance
    mock_cd.assert_called_once()


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_getattr_metadata_cache(mock_cd: MagicMock) -> None:
    caching_mod.get_metadata_cache.cache_clear()
    instance = mock_cd.return_value
    cache = caching_mod.metadata_cache
    assert cache is instance


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
def test_getattr_existence_cache(mock_cd: MagicMock) -> None:
    caching_mod.get_existence_cache.cache_clear()
    instance = mock_cd.return_value
    cache = caching_mod.existence_cache
    assert cache is instance


@pytest.mark.unit
def test_getattr_unknown_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _ = caching_mod.nonexistent_cache_xyz


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
async def test_close_caches_closes_initialized(mock_cd: MagicMock) -> None:
    caching_mod.get_response_cache.cache_clear()
    caching_mod.get_metadata_cache.cache_clear()
    caching_mod.get_existence_cache.cache_clear()

    instance_resp = MagicMock()
    instance_resp.close = AsyncMock()
    instance_meta = MagicMock()
    instance_meta.close = AsyncMock()
    instance_exists = MagicMock()
    instance_exists.close = AsyncMock()

    mock_cd.side_effect = [instance_resp, instance_meta, instance_exists]

    _ = caching_mod.get_response_cache()
    _ = caching_mod.get_metadata_cache()

    await caching_mod.close_caches()

    instance_resp.close.assert_awaited_once()
    instance_meta.close.assert_awaited_once()
    instance_exists.close.assert_not_awaited()


@pytest.mark.unit
@patch.object(caching_mod, "CachingDecorator")
async def test_close_caches_skips_uninitialized(mock_cd: MagicMock) -> None:
    caching_mod.get_response_cache.cache_clear()
    caching_mod.get_metadata_cache.cache_clear()
    caching_mod.get_existence_cache.cache_clear()

    await caching_mod.close_caches()

    mock_cd.assert_not_called()
