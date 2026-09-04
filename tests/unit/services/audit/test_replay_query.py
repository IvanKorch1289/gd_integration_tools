"""Tests for services/audit/replay_query.py (S98 — coverage push).

Async audit replay helpers: list_audit_records, replay_audit_record.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_audit_records_success() -> None:
    """list_audit_records: returns records from redis."""
    from src.backend.services.audit import replay_query

    expected = [{"id": "1-0", "data": "value"}, {"id": "1-1", "data": "value2"}]
    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        client = MagicMock()
        client.read_stream = AsyncMock(return_value=expected)
        MockProvider.return_value = client
        records = await replay_query.list_audit_records(count=50)
    assert records == expected
    client.read_stream.assert_awaited_once_with(
        stream_name="audit:events", count=50, start_id="-"
    )


@pytest.mark.asyncio
async def test_list_audit_records_empty_on_none() -> None:
    """list_audit_records: redis returns None → []."""
    from src.backend.services.audit import replay_query

    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        client = MagicMock()
        client.read_stream = AsyncMock(return_value=None)
        MockProvider.return_value = client
        records = await replay_query.list_audit_records()
    assert records == []


@pytest.mark.asyncio
async def test_list_audit_records_empty_on_exception() -> None:
    """list_audit_records: provider raises → [] + log warning."""
    from src.backend.services.audit import replay_query

    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        MockProvider.side_effect = RuntimeError("Redis down")
        records = await replay_query.list_audit_records()
    assert records == []


@pytest.mark.asyncio
async def test_replay_audit_record_success() -> None:
    """replay_audit_record: existing record → 'replayed' status."""
    from src.backend.services.audit import replay_query

    record = {"id": "1-0", "payload": "data"}
    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        client = MagicMock()
        client.read_stream = AsyncMock(return_value=[record])
        MockProvider.return_value = client
        result = await replay_query.replay_audit_record("1-0")
    assert result["status"] == "replayed"
    assert result["record_id"] == "1-0"
    assert result["new_response"] == record


@pytest.mark.asyncio
async def test_replay_audit_record_not_found() -> None:
    """replay_audit_record: redis returns empty → 'not_found' status."""
    from src.backend.services.audit import replay_query

    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        client = MagicMock()
        client.read_stream = AsyncMock(return_value=[])
        MockProvider.return_value = client
        result = await replay_query.replay_audit_record("99-0")
    assert result == {"status": "not_found", "record_id": "99-0"}


@pytest.mark.asyncio
async def test_replay_audit_record_exception() -> None:
    """replay_audit_record: exception → 'error' status + error msg."""
    from src.backend.services.audit import replay_query

    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider"
    ) as MockProvider:
        MockProvider.side_effect = RuntimeError("Redis exploded")
        result = await replay_query.replay_audit_record("1-0")
    assert result["status"] == "error"
    assert result["record_id"] == "1-0"
    assert "Redis exploded" in result["error"]


@pytest.mark.asyncio
async def test_stream_name_constant() -> None:
    """_STREAM_NAME = 'audit:events' (consistency with middleware)."""
    from src.backend.services.audit import replay_query

    assert replay_query._STREAM_NAME == "audit:events"
