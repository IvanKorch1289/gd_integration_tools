"""Unit-tests for InMemoryResilienceProfileStore."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.backend.infrastructure.resilience.profile_store_memory import InMemoryResilienceProfileStore


@dataclass
class _FakeProfile:
    name: str


@pytest.fixture
async def store() -> InMemoryResilienceProfileStore:
    return InMemoryResilienceProfileStore()


@pytest.mark.asyncio
async def test_get_missing(store: InMemoryResilienceProfileStore) -> None:
    assert await store.get("missing") is None


@pytest.mark.asyncio
async def test_upsert_and_get(store: InMemoryResilienceProfileStore) -> None:
    prof = _FakeProfile(name="p1")
    await store.upsert(prof)
    assert await store.get("p1") is prof


@pytest.mark.asyncio
async def test_tenant_override(store: InMemoryResilienceProfileStore) -> None:
    global_prof = _FakeProfile(name="p1")
    tenant_prof = _FakeProfile(name="p1")
    await store.upsert(global_prof)
    await store.upsert(tenant_prof, tenant_id="t1")
    assert await store.get("p1", tenant_id="t1") is tenant_prof
    assert await store.get("p1") is global_prof


@pytest.mark.asyncio
async def test_list(store: InMemoryResilienceProfileStore) -> None:
    await store.upsert(_FakeProfile(name="a"))
    await store.upsert(_FakeProfile(name="b"))
    results = await store.list()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_tenant_fallback(store: InMemoryResilienceProfileStore) -> None:
    await store.upsert(_FakeProfile(name="a"))
    await store.upsert(_FakeProfile(name="b"), tenant_id="t1")
    results = await store.list(tenant_id="t1")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_delete_existing(store: InMemoryResilienceProfileStore) -> None:
    await store.upsert(_FakeProfile(name="a"))
    ok = await store.delete("a")
    assert ok is True
    assert await store.get("a") is None


@pytest.mark.asyncio
async def test_delete_missing(store: InMemoryResilienceProfileStore) -> None:
    ok = await store.delete("missing")
    assert ok is False
