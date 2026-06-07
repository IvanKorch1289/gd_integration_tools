"""Unit-тесты DLQPolicy + Registry + Resolver + Cleanup job (S13 K3 W4)."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.backend.core.messaging.dlq_policy import (
    DLQPolicyRegistry,
    default_policy_registry,
)
from src.backend.infrastructure.messaging.dlq.cleanup_job import DLQCleanupJob
from src.backend.infrastructure.messaging.dlq.policy_resolver import (
    resolve_class_for_envelope,
    resolve_policy_for,
)
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope


def _make_env(**kwargs):
    defaults = {
        "transport": "http",
        "error_class": "TimeoutError",
        "error_message": "timeout",
    }
    defaults.update(kwargs)
    return DLQEnvelope(**defaults)


def test_default_registry_has_3_policies() -> None:
    policies = default_policy_registry.list_all()
    names = sorted(p.class_name for p in policies)
    assert names == ["analytics", "financial", "operational"]


def test_financial_retention_7_years() -> None:
    p = default_policy_registry.get("financial")
    assert p is not None
    assert p.retention_days == 2555
    assert p.max_replays == -1


def test_operational_default_fallback() -> None:
    reg = DLQPolicyRegistry()
    p = reg.get_or_default("unknown_class")
    assert p.class_name == "operational"


def test_resolve_class_from_envelope_dlq_class() -> None:
    env = _make_env(dlq_class="financial")
    assert resolve_class_for_envelope(env) == "financial"


def test_resolve_class_default_operational() -> None:
    env = _make_env()
    assert resolve_class_for_envelope(env) == "operational"


def test_resolve_class_from_dispatch_action_category() -> None:
    env = _make_env()
    assert (
        resolve_class_for_envelope(env, dispatch_action_category="analytics")
        == "analytics"
    )


def test_resolve_policy_returns_matching() -> None:
    env = _make_env(dlq_class="analytics")
    policy = resolve_policy_for(env, registry=default_policy_registry)
    assert policy.class_name == "analytics"
    assert policy.retention_days == 30


@pytest.mark.asyncio
async def test_cleanup_job_runs_per_policy() -> None:
    client = AsyncMock()
    client.execute = AsyncMock(return_value=[{"count()": 5}])
    fixed_now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    job = DLQCleanupJob(
        ch_client=client, registry=default_policy_registry, clock=lambda: fixed_now
    )
    stats = await job.run()
    assert stats.errors == []
    # 3 policies (financial/analytics/operational) → как минимум 3 DELETE + 3 COUNT.
    assert client.execute.await_count >= 3
    # Каждый класс получил `deleted_per_class`.
    assert "financial" in stats.deleted_per_class
    assert "operational" in stats.deleted_per_class
    assert "analytics" in stats.deleted_per_class


@pytest.mark.asyncio
async def test_cleanup_job_records_errors() -> None:
    client = AsyncMock()
    client.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
    job = DLQCleanupJob(ch_client=client, registry=default_policy_registry)
    stats = await job.run()
    assert len(stats.errors) == 3  # одна ошибка на класс
    assert "cleanup_failed" in stats.errors[0]


def test_envelope_default_dlq_class_operational() -> None:
    env = _make_env()
    assert env.dlq_class == "operational"


def test_envelope_accepts_custom_dlq_class() -> None:
    env = _make_env(dlq_class="financial")
    assert env.dlq_class == "financial"
