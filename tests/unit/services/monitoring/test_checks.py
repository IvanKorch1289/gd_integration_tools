"""Регрессии canonical connector symbols в monitoring checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.monitoring.checks import check_elasticsearch, check_workflow


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_elasticsearch_uses_canonical_client_getter() -> None:
    """Health check получает canonical singleton ElasticSearchClient."""
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    with patch(
        "src.backend.infrastructure.clients.storage.elasticsearch.get_elasticsearch_client",
        return_value=client,
    ) as client_getter:
        result = await check_elasticsearch()

    assert result is True
    client_getter.assert_called_once_with()
    client.ping.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_workflow_awaits_canonical_factory() -> None:
    """Health check использует async create_workflow_backend factory."""
    factory = AsyncMock(return_value=object())
    with patch(
        "src.backend.infrastructure.workflow.factory.create_workflow_backend",
        new=factory,
    ):
        result = await check_workflow()

    assert result is True
    factory.assert_awaited_once_with()
