"""Unit tests for NotifyProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.notify import NotifyProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_notify_success() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="delivered", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="email", template_key="welcome", recipient="u1")
        exchange = _ex({"recipient": "u1"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["notify_result"].status == "delivered"
        gateway.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_missing_recipient() -> None:
    proc = NotifyProcessor(channel="email", template_key="welcome")
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.error is not None
    assert "recipient" in exchange.error
    assert exchange.stopped


@pytest.mark.asyncio
async def test_notify_uses_body_recipient() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="delivered", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="sms", template_key="code")
        exchange = _ex({"recipient": "+7999"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        gateway.send.assert_awaited_once()
        call_kwargs = gateway.send.await_args.kwargs
        assert call_kwargs["recipient"] == "+7999"


@pytest.mark.asyncio
async def test_notify_failed_status_sets_error() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="failed", error="timeout")
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="email", template_key="x", recipient="u1")
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.error is not None
        assert "failed" in exchange.error
        assert exchange.stopped


@pytest.mark.asyncio
async def test_notify_with_context_property() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="delivered", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(
            channel="email",
            template_key="t",
            recipient="u1",
            context_property="ctx",
            result_property="res",
        )
        exchange = _ex({})
        exchange.set_property("ctx", {"name": "Alice"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert "res" in exchange.properties
        call_kwargs = gateway.send.await_args.kwargs
        assert call_kwargs["context"] == {"name": "Alice"}


def test_notify_to_spec() -> None:
    proc = NotifyProcessor(
        channel="email", template_key="welcome", recipient="u1", priority="marketing"
    )
    spec = proc.to_spec()
    assert spec == {
        "notify": {
            "channel": "email",
            "template_key": "welcome",
            "recipient": "u1",
            "priority": "marketing",
            "locale": "ru",
            "context_property": None,
            "result_property": "notify_result",
        }
    }
