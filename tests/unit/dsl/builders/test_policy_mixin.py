"""Unit-тесты PolicyMixin chainable API — Wave [wave:s5/k3-w7-policy-chainable]."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.builders.policy_mixin import PolicyMarkerProcessor, PolicyMixin


class _FakeBuilder(PolicyMixin):
    """Minimal builder-stub для тестов миксина (без полной dataclass-структуры)."""

    __slots__ = ("_processors",)

    def __init__(self) -> None:
        self._processors = []


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "policy_chainable_enabled", True)


def test_single_cache_policy() -> None:
    builder = _FakeBuilder()
    result = builder.policy.cache(ttl_seconds=120)
    assert result is builder
    assert len(builder._processors) == 1
    p = builder._processors[0]
    assert isinstance(p, PolicyMarkerProcessor)
    assert p.policy_name == "cache"
    assert p.params == {"ttl_seconds": 120, "key": None, "backend": "redis"}


def test_chained_two_policies() -> None:
    builder = _FakeBuilder()
    result = builder.policy.cache(ttl_seconds=60).policy.circuit_breaker(threshold=10)
    assert result is builder
    assert len(builder._processors) == 2
    assert builder._processors[0].policy_name == "cache"
    assert builder._processors[1].policy_name == "circuit_breaker"


def test_chained_three_policies() -> None:
    builder = _FakeBuilder()
    result = (
        builder.policy.cache(ttl_seconds=60)
        .policy.circuit_breaker(threshold=5)
        .policy.rate_limit(rate=100, per_seconds=1)
    )
    assert result is builder
    assert len(builder._processors) == 3
    names = [p.policy_name for p in builder._processors]
    assert names == ["cache", "circuit_breaker", "rate_limit"]


@pytest.mark.asyncio
async def test_resilience_coordinator_register_attempted() -> None:
    """Убедиться, что process() пытается интегрироваться с ResilienceCoordinator
    без падения при его отсутствии."""

    from src.backend.dsl.engine.exchange import Exchange, Message

    proc = PolicyMarkerProcessor(
        policy_name="rate_limit", params={"rate": 10}, enabled=True
    )
    ex = Exchange(in_message=Message(body={}, headers={}))
    await proc.process(ex, AsyncMock())
    applied = ex.properties.get("_policies_applied")
    assert applied and len(applied) == 1
    assert applied[0]["name"] == "rate_limit"
    assert applied[0]["params"]["rate"] == 10
