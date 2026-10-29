"""Unit tests for CDC REST routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

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
            profile="pg-prod",
            tables=["users", "orders"],
            strategy="polling",
            interval=5.0,
            batch_size=100,
            timestamp_column="updated_at",
            channel=None,
            target_action="cdc.handler",
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
            profile="pg-dev",
            tables=["logs"],
            strategy="polling",
            interval=5.0,
            batch_size=100,
            timestamp_column="updated_at",
            channel=None,
            target_action=None,
        )

    @pytest.mark.asyncio
    async def test_strategy_is_forwarded_to_client(self) -> None:
        """ADR-0384: REST позволяет выбрать стратегию CDC."""
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock(return_value="sub-777")
        db.set_cdc_client_provider(mock_client)

        request = CDCSubscribeRequest(
            profile="pg-dev",
            tables=["logs"],
            strategy="kafka",
            interval=15.0,
            batch_size=50,
            channel="cdc_logs",
        )
        await create_subscription(request)

        kwargs = mock_client.subscribe.await_args.kwargs
        assert kwargs["strategy"] == "kafka"
        assert kwargs["interval"] == 15.0
        assert kwargs["batch_size"] == 50
        assert kwargs["channel"] == "cdc_logs"


class TestCreateSubscriptionValidation:
    """ADR-0384: валидация параметров подписки на REST-границе."""

    def test_tables_must_not_be_empty(self) -> None:
        """Пустой список таблиц отклоняется (было: подписка без таблиц)."""
        with pytest.raises(ValidationError):
            CDCSubscribeRequest(profile="pg-dev", tables=[])

    def test_tables_is_required(self) -> None:
        """tables — обязательное поле."""
        with pytest.raises(ValidationError):
            CDCSubscribeRequest(profile="pg-dev")

    def test_unknown_strategy_rejected(self) -> None:
        """Неизвестная стратегия отклоняется."""
        with pytest.raises(ValidationError):
            CDCSubscribeRequest(profile="pg-dev", tables=["logs"], strategy="nope")

    def test_interval_must_be_positive(self) -> None:
        """Неположительный интервал отклоняется."""
        with pytest.raises(ValidationError):
            CDCSubscribeRequest(profile="pg-dev", tables=["logs"], interval=0)

    @pytest.mark.parametrize("batch_size", [0, -1, 10_000_000])
    def test_batch_size_bounds(self, batch_size: int) -> None:
        """batch_size вне диапазона отклоняется."""
        with pytest.raises(ValidationError):
            CDCSubscribeRequest(
                profile="pg-dev", tables=["logs"], batch_size=batch_size
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
