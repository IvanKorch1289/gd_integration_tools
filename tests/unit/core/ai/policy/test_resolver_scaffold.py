"""Smoke-тесты scaffold :class:`PolicyResolver` (Sprint 25 W2, ADR-NEW-20).

В scaffold-фазе resolver всегда возвращает ``None`` (полная реализация —
Wave S25 W2 после accept ADR-NEW-20). Тесты проверяют API-контракт и
glob-matcher логику.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.policy.resolver import (
    PolicyNotResolvedError,
    PolicyResolver,
)


@pytest.mark.asyncio
async def test_resolver_returns_none_in_scaffold() -> None:
    """Scaffold-резолвер не находит policy (S25 W2 carryover)."""
    resolver = PolicyResolver()
    policy = await resolver.resolve(workflow_id="credit_check", tenant_id="t-1")
    assert policy is None


def test_resolver_glob_matcher() -> None:
    """``_matches`` поддерживает fnmatch glob-паттерны."""
    resolver = PolicyResolver()
    assert resolver._matches("credit_check*", "credit_check_v2") is True
    assert resolver._matches("credit_check", "credit_check") is True
    assert resolver._matches("credit_check", "credit_check_v2") is False
    assert resolver._matches("*", "anything") is True
    assert resolver._matches("premium*", "premium_tenant_1") is True
    assert resolver._matches("premium*", "basic_tenant") is False


def test_policy_not_resolved_error() -> None:
    """PolicyNotResolvedError сохраняет workflow_id + tenant_id."""
    err = PolicyNotResolvedError(workflow_id="credit_check", tenant_id="t-1")
    assert err.workflow_id == "credit_check"
    assert err.tenant_id == "t-1"
    assert "credit_check" in str(err)
    assert "t-1" in str(err)


def test_resolver_reload_clears_cache() -> None:
    """``reload()`` очищает RAM-cache."""
    resolver = PolicyResolver()
    resolver._cache[("credit_check", "t-1")] = "dummy"  # type: ignore[assignment]
    assert len(resolver._cache) == 1
    resolver.reload()
    assert len(resolver._cache) == 0
