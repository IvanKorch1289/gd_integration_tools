"""Тесты RuleEngineRegistry (Wave [wave:s8/k3-rule-engine-finale]).

Используют fake-репозиторий и controllable clock — проверяют cache hit/miss,
invalidate и hot-reload через feature flag.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.core.interfaces.rule_engine import (
    RuleEngineRepository,
    RulesetDoc,
)
from src.backend.services.integrations.rule_engine.registry import (
    HOT_RELOAD_TTL_SECONDS,
    RuleEngineRegistry,
)

pytestmark = pytest.mark.asyncio


class FakeRepo(RuleEngineRepository):
    """In-memory fake-реализация Protocol для тестов registry."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str | None], RulesetDoc] = {}
        self.get_calls: int = 0

    def put(self, doc: RulesetDoc) -> None:
        self._docs[(doc.name, doc.tenant_id)] = doc

    async def get(
        self,
        name: str,
        *,
        version: str | None = None,
        tenant_id: str | None = None,
    ) -> RulesetDoc | None:
        self.get_calls += 1
        return self._docs.get((name, tenant_id))

    async def list_active(
        self, *, tenant_id: str | None = None
    ) -> list[RulesetDoc]:
        return [
            d for d in self._docs.values()
            if (tenant_id is None or d.tenant_id == tenant_id) and d.enabled
        ]

    async def upsert(self, doc: RulesetDoc) -> RulesetDoc:
        self._docs[(doc.name, doc.tenant_id)] = doc
        return doc

    async def delete(
        self, name: str, version: str, *, tenant_id: str | None = None
    ) -> bool:
        key = (name, tenant_id)
        if key in self._docs:
            del self._docs[key]
            return True
        return False


class FakeFlags:
    """Минимальный feature-flag объект для тестов."""

    def __init__(self, hot_reload: bool = False) -> None:
        self.rule_engine_hot_reload = hot_reload


_VALID_YAML = """
name: credit_scoring
rules:
  - id: high_risk
    condition: "score < 500"
    action: decline
default_action: approve
"""


async def test_get_active_caches_after_first_load() -> None:
    """Второй вызов не идёт в репо (cache hit)."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="rs", yaml_body=_VALID_YAML))
    registry = RuleEngineRegistry(repo, FakeFlags())

    parsed1 = await registry.get_active("rs")
    parsed2 = await registry.get_active("rs")

    assert parsed1 == parsed2
    assert parsed1 is not None and parsed1["name"] == "credit_scoring"
    assert repo.get_calls == 1


async def test_get_active_returns_none_for_missing() -> None:
    """Отсутствующий ruleset → None и кэш не растёт."""
    registry = RuleEngineRegistry(FakeRepo(), FakeFlags())

    result = await registry.get_active("nonexistent")

    assert result is None
    assert registry.cache_size() == 0


async def test_invalidate_by_name() -> None:
    """invalidate("rs") очищает только эту запись."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="a", yaml_body=_VALID_YAML))
    repo.put(RulesetDoc(name="b", yaml_body=_VALID_YAML))
    registry = RuleEngineRegistry(repo, FakeFlags())
    await registry.get_active("a")
    await registry.get_active("b")
    assert registry.cache_size() == 2

    removed = registry.invalidate("a")

    assert removed == 1
    assert registry.cache_size() == 1


async def test_invalidate_all() -> None:
    """invalidate() без имени чистит весь кэш."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="a", yaml_body=_VALID_YAML))
    repo.put(RulesetDoc(name="b", yaml_body=_VALID_YAML))
    registry = RuleEngineRegistry(repo, FakeFlags())
    await registry.get_active("a")
    await registry.get_active("b")

    removed = registry.invalidate()

    assert removed == 2
    assert registry.cache_size() == 0


async def test_hot_reload_re_fetches_after_ttl() -> None:
    """При hot_reload=True и истёкшем TTL repo вызывается повторно."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="rs", yaml_body=_VALID_YAML))
    flags = FakeFlags(hot_reload=True)

    fixed = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    times: list[datetime] = [fixed]

    def clock() -> datetime:
        return times[-1]

    registry = RuleEngineRegistry(repo, flags, clock=clock)

    await registry.get_active("rs")
    assert repo.get_calls == 1

    # Сдвигаем clock за пределы TTL.
    times.append(fixed + timedelta(seconds=HOT_RELOAD_TTL_SECONDS + 1))
    await registry.get_active("rs")

    assert repo.get_calls == 2


async def test_hot_reload_off_does_not_refetch() -> None:
    """При hot_reload=False повторного похода в repo нет даже после TTL."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="rs", yaml_body=_VALID_YAML))

    fixed = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    times: list[datetime] = [fixed]
    registry = RuleEngineRegistry(
        repo, FakeFlags(hot_reload=False), clock=lambda: times[-1]
    )

    await registry.get_active("rs")
    times.append(fixed + timedelta(hours=1))
    await registry.get_active("rs")

    assert repo.get_calls == 1


async def test_invalid_yaml_root_returns_none() -> None:
    """YAML, корень которого не dict (напр., список), возвращает None."""
    repo = FakeRepo()
    repo.put(RulesetDoc(name="rs", yaml_body="- 1\n- 2\n"))
    registry = RuleEngineRegistry(repo, FakeFlags())

    result = await registry.get_active("rs")

    assert result is None
