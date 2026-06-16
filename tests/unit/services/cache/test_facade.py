"""Unit-тесты UnifiedCacheFacade (P1 S133 W4)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.security.capabilities import CapabilityDeniedError
from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.services.cache.facade import CacheResult, UnifiedCacheFacade


class _SimpleBackend(CacheBackend):
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.fail_next: bool = False

    async def get(self, key: str) -> bytes | None:
        if self.fail_next:
            raise RuntimeError("boom")
        return self._data.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        if self.fail_next:
            raise RuntimeError("boom")
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        prefix = pattern.rstrip("*")
        for key in list(self._data):
            if key.startswith(prefix):
                del self._data[key]

    async def exists(self, key: str) -> bool:
        return key in self._data


@pytest.fixture()
def primary() -> _SimpleBackend:
    return _SimpleBackend()


@pytest.fixture()
def facade(primary: _SimpleBackend, tmp_path: Path) -> UnifiedCacheFacade:
    def _check(plugin: str, capability: str, scope: str | None = None) -> None:
        assert plugin == "test_plugin"
        if capability not in {"cache.read", "cache.write"}:
            raise CapabilityDeniedError(plugin, capability, scope)

    return UnifiedCacheFacade(
        primary=primary,
        memory_fallback=MemoryBackend(maxsize=10),
        disk_fallback=DiskCacheBackend(base_path=tmp_path / "disk"),
        capability_check=_check,
        plugin="test_plugin",
    )


@pytest.mark.asyncio
async def test_get_hit_primary(facade: UnifiedCacheFacade) -> None:
    await facade.set("k1", b"v1")
    result = await facade.get("k1")
    assert isinstance(result, CacheResult)
    assert result.hit is True
    assert result.value == b"v1"
    assert result.backend == "primary"


@pytest.mark.asyncio
async def test_get_fallback_to_memory(
    primary: _SimpleBackend, facade: UnifiedCacheFacade
) -> None:
    await facade.set("k2", b"v2")
    primary.fail_next = True
    result = await facade.get("k2")
    assert result.hit is True
    assert result.value == b"v2"
    assert result.backend == "memory"


@pytest.mark.asyncio
async def test_get_fallback_to_disk(
    primary: _SimpleBackend, facade: UnifiedCacheFacade
) -> None:
    await facade.set("k3", b"v3")
    primary.fail_next = True
    facade._memory._cache = {}  # noqa: SLF001
    result = await facade.get("k3")
    assert result.hit is True
    assert result.value == b"v3"
    assert result.backend == "disk"


@pytest.mark.asyncio
async def test_get_miss(facade: UnifiedCacheFacade) -> None:
    result = await facade.get("missing")
    assert result.hit is False
    assert result.value is None
    assert result.backend == "none"


@pytest.mark.asyncio
async def test_set_and_delete(facade: UnifiedCacheFacade) -> None:
    await facade.set("d1", b"data")
    assert (await facade.get("d1")).value == b"data"
    await facade.delete("d1")
    assert (await facade.get("d1")).hit is False


@pytest.mark.asyncio
async def test_delete_pattern_only_primary_and_memory(
    primary: _SimpleBackend, facade: UnifiedCacheFacade
) -> None:
    await facade.set("ns.a", b"1")
    await facade.set("ns.b", b"2")
    await facade.set("other", b"3")
    await facade.delete_pattern("ns.*")
    # disk fallback still holds the value because pattern delete is no-op there
    assert (await facade.get("ns.a")).backend == "disk"
    assert (await facade.get("ns.b")).backend == "disk"
    assert (await facade.get("other")).value == b"3"


@pytest.mark.asyncio
async def test_set_without_permission(facade: UnifiedCacheFacade) -> None:
    def _check_denied(plugin: str, capability: str, scope: str | None = None) -> None:
        if capability != "cache.read":
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
            )

    facade._check = _check_denied  # noqa: SLF001
    with pytest.raises(CapabilityDeniedError):
        await facade.set("x", b"y")


@pytest.mark.asyncio
async def test_get_without_permission(facade: UnifiedCacheFacade) -> None:
    def _check_write(plugin: str, capability: str, scope: str | None = None) -> None:
        if capability != "cache.write":
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
            )

    facade._check = _check_write  # noqa: SLF001
    with pytest.raises(CapabilityDeniedError):
        await facade.get("x")


@pytest.mark.asyncio
async def test_namespace_isolation(facade: UnifiedCacheFacade) -> None:
    await facade.set("same", b"A", namespace="ns1")
    await facade.set("same", b"B", namespace="ns2")
    assert (await facade.get("same", namespace="ns1")).value == b"A"
    assert (await facade.get("same", namespace="ns2")).value == b"B"


@pytest.mark.asyncio
async def test_set_propagates_to_all_tiers(
    primary: _SimpleBackend, facade: UnifiedCacheFacade
) -> None:
    await facade.set("multi", b"v")
    assert await primary.exists("default:multi")
    assert await facade._memory.exists("default:multi")  # noqa: SLF001
    assert await facade._disk.exists("default:multi")  # noqa: SLF001
