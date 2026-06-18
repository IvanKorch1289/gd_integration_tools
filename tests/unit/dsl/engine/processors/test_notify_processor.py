# ruff: noqa: S101
"""Unit tests for NotifyProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.notify import NotifyProcessor


def _make_exchange(
    body: Any = None, headers: dict[str, Any] | None = None
) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def test_to_spec_round_trip() -> None:
    proc = NotifyProcessor(
        channel="email",
        template_key="welcome",
        recipient="user@example.com",
        priority="marketing",
        locale="en",
        context_property="ctx",
        result_property="res",
    )
    spec = proc.to_spec()
    assert spec == {
        "notify": {
            "channel": "email",
            "template_key": "welcome",
            "recipient": "user@example.com",
            "priority": "marketing",
            "locale": "en",
            "context_property": "ctx",
            "result_property": "res",
        }
    }


@pytest.mark.asyncio
async def test_process_success() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="sent", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="email", template_key="welcome", recipient="u1")
        exchange = _make_exchange({"recipient": "u1"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["notify_result"].status == "sent"
        gateway.send.assert_awaited_once()
        assert not exchange.stopped
        assert exchange.error is None


@pytest.mark.asyncio
async def test_process_failed_sets_error_and_stops() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="failed", error="timeout")
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="email", template_key="welcome", recipient="u1")
        exchange = _make_exchange({})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.error is not None
        assert "failed" in exchange.error
        assert exchange.stopped


@pytest.mark.asyncio
async def test_process_missing_recipient_sets_error_and_stops() -> None:
    proc = NotifyProcessor(channel="email", template_key="welcome")
    exchange = _make_exchange({})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "recipient" in exchange.error
    assert exchange.stopped


@pytest.mark.asyncio
async def test_process_uses_context_property_when_set() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="sent", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(
            channel="sms",
            template_key="code",
            recipient="+7999",
            context_property="ctx",
        )
        exchange = _make_exchange({"other": "data"})
        exchange.set_property("ctx", {"name": "Alice"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        call_kwargs = gateway.send.await_args.kwargs
        assert call_kwargs["context"] == {"name": "Alice"}


@pytest.mark.asyncio
async def test_process_uses_body_when_no_context_property() -> None:
    with patch(
        "src.backend.core.notifications.get_gateway"
    ) as mock_get:
        gateway = AsyncMock()
        gateway.send.return_value = AsyncMock(status="sent", error=None)
        mock_get.return_value = gateway

        proc = NotifyProcessor(channel="sms", template_key="code", recipient="+7999")
        exchange = _make_exchange({"name": "Bob"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        call_kwargs = gateway.send.await_args.kwargs
        assert call_kwargs["context"] == {"name": "Bob"}
