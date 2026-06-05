"""Unit-tests for TenantCacheBackend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.cache.tenant_wrapper import (
    DEFAULT_UNSCOPED_PREFIX,
    TenantCacheBackend,
    _matches_pattern,
)


class _FakeTenant:
    tenant_id = "bank_a"


@pytest.fixture
def mock_backend() -> MagicMock:
    return MagicMock(
        get=AsyncMock(),
        set=AsyncMock(),
        delete=AsyncMock(),
        delete_pattern=AsyncMock(),
        exists=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _enable_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.feature_flags",
        MagicMock(tenant_cache_prefix_enabled=True),
    )


@pytest.mark.asyncio
async def test_get_with_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: _FakeTenant(),
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.get("foo")
    mock_backend.get.assert_awaited_once_with("tenant:bank_a:foo")


@pytest.mark.asyncio
async def test_get_without_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: None,
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.get("foo")
    mock_backend.get.assert_awaited_once_with(DEFAULT_UNSCOPED_PREFIX + "foo")


@pytest.mark.asyncio
async def test_set_with_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: _FakeTenant(),
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.set("k", b"v", ttl=60)
    mock_backend.set.assert_awaited_once_with("tenant:bank_a:k", b"v", ttl=60)


@pytest.mark.asyncio
async def test_delete_with_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: _FakeTenant(),
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.delete("a", "b")
    mock_backend.delete.assert_awaited_once_with("tenant:bank_a:a", "tenant:bank_a:b")


@pytest.mark.asyncio
async def test_delete_empty_skips(mock_backend: MagicMock) -> None:
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.delete()
    mock_backend.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_pattern_with_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: _FakeTenant(),
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.delete_pattern("user:*")
    mock_backend.delete_pattern.assert_awaited_once_with("tenant:bank_a:user:*")


@pytest.mark.asyncio
async def test_exists_with_tenant(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.current_tenant",
        lambda: _FakeTenant(),
    )
    wrapper = TenantCacheBackend(mock_backend)
    await wrapper.exists("k")
    mock_backend.exists.assert_awaited_once_with("tenant:bank_a:k")


def test_prefix_disabled_feature_flag(mock_backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.tenant_wrapper.feature_flags",
        MagicMock(tenant_cache_prefix_enabled=False),
    )
    wrapper = TenantCacheBackend(mock_backend)
    assert wrapper._prefix() == ""
    assert wrapper._scoped("key") == "key"


def test_wrapped_property(mock_backend: MagicMock) -> None:
    wrapper = TenantCacheBackend(mock_backend)
    assert wrapper.wrapped is mock_backend


def test_matches_pattern() -> None:
    assert _matches_pattern("foo.bar", "foo.*")
    assert not _matches_pattern("foo.bar", "baz.*")
