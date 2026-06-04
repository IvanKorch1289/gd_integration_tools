"""Unit-тесты PromptVersionService (Sprint 9 K4 W4)."""

from __future__ import annotations

import pytest

from src.backend.services.ai.prompt_versioning import (
    InMemoryPromptVersionStore,
    PromptVersionService,
)


@pytest.fixture
def service() -> PromptVersionService:
    return PromptVersionService(store=InMemoryPromptVersionStore())


@pytest.mark.asyncio
async def test_create_version_auto_bumps(service: PromptVersionService) -> None:
    v1 = await service.create_version(name="x", body="hi")
    v2 = await service.create_version(name="x", body="hello")
    assert v1.version == 1
    assert v2.version == 2


@pytest.mark.asyncio
async def test_list_versions_sorted(service: PromptVersionService) -> None:
    await service.create_version(name="a", body="b1")
    await service.create_version(name="a", body="b2")
    versions = await service.list_versions("a")
    assert [v.version for v in versions] == [1, 2]


@pytest.mark.asyncio
async def test_set_active_deactivates_others(service: PromptVersionService) -> None:
    await service.create_version(name="a", body="b1")
    await service.create_version(name="a", body="b2")
    await service.set_active("a", 2)
    active = await service.get_active("a")
    assert active is not None
    assert active.version == 2


@pytest.mark.asyncio
async def test_rollback_to_previous(service: PromptVersionService) -> None:
    await service.create_version(name="a", body="b1")
    await service.create_version(name="a", body="b2")
    await service.set_active("a", 2)
    rolled = await service.rollback("a")
    assert rolled is not None
    assert rolled.version == 1


@pytest.mark.asyncio
async def test_rollback_returns_none_if_only_one(service: PromptVersionService) -> None:
    await service.create_version(name="a", body="b1")
    rolled = await service.rollback("a")
    assert rolled is None


@pytest.mark.asyncio
async def test_compare_computes_diffs(service: PromptVersionService) -> None:
    a = await service.create_version(name="x", body="b1")
    b = await service.create_version(name="x", body="b2")
    await service.update_metrics(name="x", version=a.version, metrics={"accuracy": 0.8})
    await service.update_metrics(name="x", version=b.version, metrics={"accuracy": 0.9})
    comparison = await service.compare(
        name="x", version_a=a.version, version_b=b.version
    )
    assert comparison.metric_diffs["accuracy"] == pytest.approx(0.1, abs=1e-6)


@pytest.mark.asyncio
async def test_create_duplicate_version_raises(service: PromptVersionService) -> None:
    store = InMemoryPromptVersionStore()
    from src.backend.services.ai.prompt_versioning import PromptVersion

    await store.create(PromptVersion(name="x", version=1, body="b"))
    with pytest.raises(ValueError):
        await store.create(PromptVersion(name="x", version=1, body="b"))
