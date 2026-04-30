"""W23 — DedupeStore (memory backend)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.services.sources.idempotency import DedupeStore, MemoryDedupeStore


def test_protocol_compliance() -> None:
    assert isinstance(MemoryDedupeStore(), DedupeStore)


@pytest.mark.asyncio
async def test_first_call_not_dup() -> None:
    store = MemoryDedupeStore()
    assert await store.is_duplicate("ns", "id-1") is False


@pytest.mark.asyncio
async def test_second_call_is_dup() -> None:
    store = MemoryDedupeStore()
    await store.is_duplicate("ns", "id-1")
    assert await store.is_duplicate("ns", "id-1") is True


@pytest.mark.asyncio
async def test_namespace_isolation() -> None:
    store = MemoryDedupeStore()
    await store.is_duplicate("ns-a", "id-1")
    # Тот же event_id, но другая ns — не дубль.
    assert await store.is_duplicate("ns-b", "id-1") is False
