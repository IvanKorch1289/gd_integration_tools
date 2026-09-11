"""Focused tests for hitl_pubsub (PERF-6.6 Sprint 17 coverage ratchet).

Coverage target: hitl_pubsub.py 45% → 70%+.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.workflows.hitl_pubsub import (
    _channel_name,
    publish_hitl_resolved,
)


def test_channel_name_format() -> None:
    """_channel_name(tenant_id) → 'hitl:resolved:{tenant_id}'."""
    assert _channel_name("acme") == "hitl:resolved:acme"
    assert _channel_name("tenant-1") == "hitl:resolved:tenant-1"


def test_channel_name_special_chars() -> None:
    """_channel_name для спец-символов."""
    assert _channel_name("abc123") == "hitl:resolved:abc123"


def test_channel_name_with_uuid_tenant() -> None:
    """_channel_name с UUID-tenant."""
    assert _channel_name("550e8400-e29b-41d4-a716-446655440000") == "hitl:resolved:550e8400-e29b-41d4-a716-446655440000"


class _FakeRedisFactory:
    """Factory that mimics get_redis_client()() → await get_client() → redis."""

    def __init__(self, redis_client: MagicMock) -> None:
        self._redis = redis_client

    def __call__(self) -> _FakeRedisFactory:
        return self

    async def get_client(self, name: str) -> MagicMock:
        return self._redis


@pytest.mark.asyncio
async def test_publish_hitl_resolved_basic() -> None:
    """publish_hitl_resolved — publishes to redis pub/sub."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        result = await publish_hitl_resolved(
            signal_id="sig-123",
            workflow_id="wf-1",
            tenant_id="acme",
            action="approve",
            resolved_by="alice",
        )
        assert result == 1
        assert mock_redis.publish.called
        call_args = mock_redis.publish.call_args
        assert call_args.args[0] == "hitl:resolved:acme"


@pytest.mark.asyncio
async def test_publish_hitl_resolved_payload_format() -> None:
    """publish_hitl_resolved payload содержит signal_id и event_type."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        await publish_hitl_resolved(
            signal_id="sig-456",
            workflow_id="wf-1",
            tenant_id="acme",
            action="approve",
            resolved_by="alice",
        )
        body = mock_redis.publish.call_args.args[1]
        parsed = json.loads(body)
        assert parsed["signal_id"] == "sig-456"
        assert parsed["workflow_id"] == "wf-1"
        assert parsed["action"] == "approve"
        assert parsed["resolved_by"] == "alice"
        assert parsed["event_type"] == "hitl.resolved"


@pytest.mark.asyncio
async def test_publish_hitl_resolved_with_payload() -> None:
    """publish_hitl_resolved с custom payload dict."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    custom_payload = {"form": "data", "comment": "approved by manager"}

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        await publish_hitl_resolved(
            signal_id="sig-789",
            workflow_id="wf-1",
            tenant_id="acme",
            action="reject",
            resolved_by="bob",
            payload=custom_payload,
        )
        body = mock_redis.publish.call_args.args[1]
        parsed = json.loads(body)
        assert parsed["payload"] == custom_payload


@pytest.mark.asyncio
async def test_publish_hitl_resolved_redis_error_returns_zero() -> None:
    """publish_hitl_resolved с redis error → returns 0 (best-effort)."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(side_effect=Exception("connection lost"))

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        result = await publish_hitl_resolved(
            signal_id="sig-error",
            workflow_id="wf-1",
            tenant_id="acme",
            action="approve",
            resolved_by="alice",
        )
        assert result == 0


@pytest.mark.asyncio
async def test_publish_hitl_resolved_factory_error_returns_zero() -> None:
    """publish_hitl_resolved с factory error (no redis) → returns 0."""
    with patch(
        "src.backend.core.api.storage.get_redis_client",
        side_effect=Exception("Redis not configured"),
    ):
        result = await publish_hitl_resolved(
            signal_id="sig-factory-err",
            workflow_id="wf-1",
            tenant_id="acme",
            action="approve",
            resolved_by="alice",
        )
        assert result == 0


@pytest.mark.asyncio
async def test_publish_hitl_resolved_different_tenants() -> None:
    """publish для разных tenant_id → разные channels."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        await publish_hitl_resolved(
            signal_id="s1", workflow_id="w1", tenant_id="t1",
            action="approve", resolved_by="alice"
        )
        await publish_hitl_resolved(
            signal_id="s2", workflow_id="w2", tenant_id="t2",
            action="approve", resolved_by="bob"
        )
        assert mock_redis.publish.call_args_list[0].args[0] == "hitl:resolved:t1"
        assert mock_redis.publish.call_args_list[1].args[0] == "hitl:resolved:t2"


@pytest.mark.asyncio
async def test_publish_hitl_resolved_awaited() -> None:
    """publish_hitl_resolved вызывает client.publish с await."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch(
        "src.backend.core.api.storage.get_redis_client",
        return_value=_FakeRedisFactory(mock_redis),
    ):
        await publish_hitl_resolved(
            signal_id="s1", workflow_id="w1", tenant_id="t1",
            action="approve", resolved_by="alice"
        )
        assert mock_redis.publish.await_count == 1
