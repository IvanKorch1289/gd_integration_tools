"""Unit tests for CDC REST routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.di.providers import db
from src.backend.entrypoints.cdc.cdc_routes import (
    CDCSubscribeRequest,
    CDCSubscribeResponse,
    create_subscription,
    delete_subscription,
    list_subscriptions,
)


@pytest.fixture(autouse=True)
def reset_cdc_override() -> Any:
    """Ensure CDC provider override is cleaned after each test."""
    yield
    db.set_cdc_client_provider(None)  # type: ignore[arg-type]


class TestCreateSubscription:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub-123")
        db.set_cdc_client_provider(mock_client)

        request = CDCSubscribeRequest(
            profile="pg-prod", tables=["users", "orders"], target_action="cdc.handler"
        )
        response = await create_subscription(request)

        assert isinstance(response, CDCSubscribeResponse)
        assert response.subscription_id == "sub-123"
        assert response.profile == "pg-prod"
        assert response.tables == ["users", "orders"]
        assert response.target_action == "cdc.handler"
        mock_client.subscribe.assert_awaited_once_with(
            profile="pg-prod", tables=["users", "orders"], target_action="cdc.handler"
        )

    @pytest.mark.asyncio
    async def test_no_target_action(self) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub-456")
        db.set_cdc_client_provider(mock_client)

        request = CDCSubscribeRequest(profile="pg-dev", tables=["logs"])
        response = await create_subscription(request)

        assert response.subscription_id == "sub-456"
        assert response.target_action is None
        mock_client.subscribe.assert_awaited_once_with(
            profile="pg-dev", tables=["logs"], target_action=None
        )


class TestDeleteSubscription:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        mock_client = MagicMock()
        mock_client.unsubscribe = AsyncMock(return_value=True)
        db.set_cdc_client_provider(mock_client)

        result = await delete_subscription("sub-123")

        assert result == {"deleted": True, "subscription_id": "sub-123"}
        mock_client.unsubscribe.assert_awaited_once_with("sub-123")

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_client = MagicMock()
        mock_client.unsubscribe = AsyncMock(return_value=False)
        db.set_cdc_client_provider(mock_client)

        result = await delete_subscription("sub-missing")

        assert result == {"deleted": False, "subscription_id": "sub-missing"}


class TestListSubscriptions:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        mock_client = MagicMock()
        mock_client.list_subscriptions.return_value = [
            {"id": "sub-1", "profile": "pg"},
            {"id": "sub-2", "profile": "oracle"},
        ]
        db.set_cdc_client_provider(mock_client)

        result = await list_subscriptions()

        assert len(result) == 2
        assert result[0]["id"] == "sub-1"

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        mock_client = MagicMock()
        mock_client.list_subscriptions.return_value = []
        db.set_cdc_client_provider(mock_client)

        result = await list_subscriptions()

        assert result == []
