# ruff: noqa: S101
"""Unit tests for NotifyGatewayActions (services/ops/notify_actions.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.ops.notify_actions import (
    NotifyGatewayActions,
    get_notify_gateway_actions,
    register_notify_actions,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.ops.notify_actions as _mod

    _mod._actions = None
    yield
    _mod._actions = None


@pytest.fixture()
def actions() -> NotifyGatewayActions:
    return NotifyGatewayActions()


# ── send channels ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_delegates_to_gateway(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        result = await actions.send(channel="email", to="a@b.com")
        gateway.send.assert_awaited_once_with(channel="email", to="a@b.com")
        assert result == gateway.send.return_value


@pytest.mark.asyncio
async def test_email_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.email(subject="hi", body="hello")
        gateway.send.assert_awaited_once_with(
            channel="email", subject="hi", body="hello"
        )


@pytest.mark.asyncio
async def test_telegram_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.telegram(chat_id="123")
        gateway.send.assert_awaited_once_with(channel="telegram", chat_id="123")


@pytest.mark.asyncio
async def test_slack_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.slack(text="msg")
        gateway.send.assert_awaited_once_with(channel="slack", text="msg")


@pytest.mark.asyncio
async def test_teams_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.teams(text="msg")
        gateway.send.assert_awaited_once_with(channel="teams", text="msg")


@pytest.mark.asyncio
async def test_sms_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.sms(phone="+7999")
        gateway.send.assert_awaited_once_with(channel="sms", phone="+7999")


@pytest.mark.asyncio
async def test_webhook_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.webhook(url="http://hook")
        gateway.send.assert_awaited_once_with(channel="webhook", url="http://hook")


@pytest.mark.asyncio
async def test_express_channel(actions: NotifyGatewayActions) -> None:
    with patch("src.backend.core.providers_registry.get_provider") as mock_get_provider:
        gateway = AsyncMock()
        mock_get_provider.return_value = gateway
        await actions.express(chat_id="c1")
        gateway.send.assert_awaited_once_with(channel="express", chat_id="c1")


# ── register_notify_actions ─────────────────────────────────────


@pytest.mark.asyncio
async def test_register_notify_actions_default_prefix() -> None:
    registry = MagicMock()
    names = register_notify_actions(registry)
    assert "notifyv2.send" in names
    assert "notifyv2.email" in names
    assert "notifyv2.telegram" in names
    assert "notifyv2.slack" in names
    assert "notifyv2.teams" in names
    assert "notifyv2.sms" in names
    assert "notifyv2.webhook" in names
    assert "notifyv2.express" in names
    registry.register_many.assert_called_once()


@pytest.mark.asyncio
async def test_register_notify_actions_override() -> None:
    registry = MagicMock()
    names = register_notify_actions(registry, override=True)
    assert "notify.send" in names
    assert "notify.email" in names


# ── singleton ───────────────────────────────────────────────────


def test_get_notify_gateway_actions_singleton() -> None:
    a1 = get_notify_gateway_actions()
    a2 = get_notify_gateway_actions()
    assert a1 is a2
