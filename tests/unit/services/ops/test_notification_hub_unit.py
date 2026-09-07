"""Тесты NotificationHub (T3 ratchet: notification_hub.py 43%→≥90%).

Thin-adapter над Gateway: send-трансляция (template_key legacy-slug,
status queued→sent), пер-канальные методы, broadcast, express_event
форматирование, _slug-контракт. Gateway мокается через patch
get_gateway.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.ops.notification_hub import (
    NotificationHub,
    NotificationRequest,
    _slug,
)


@pytest.fixture
def hub() -> NotificationHub:
    return NotificationHub()


def _gateway_mock(status: str = "queued", request_id: str = "req-1") -> AsyncMock:
    gw = AsyncMock()
    result = SimpleNamespace(status=status, request_id=request_id)
    gw.send = AsyncMock(return_value=result)
    return gw


@pytest.mark.asyncio
async def test_send_translates_to_gateway_contract(hub: NotificationHub) -> None:
    """send: channel/to/subject/message -> legacy template_key + context."""
    gw = _gateway_mock()
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        result = await hub.send("email", "user@bank.ru", subject="КД №123", message="тело")

    assert result["status"] == "sent"  # queued -> sent
    assert result["request_id"] == "req-1"
    kwargs = gw.send.await_args.kwargs
    assert kwargs["channel"] == "email"
    assert kwargs["recipient"] == "user@bank.ru"
    assert kwargs["template_key"] == "legacy:email:кд-123"  # subject=«КД №123»
    assert kwargs["context"]["message"] == "тело"


@pytest.mark.asyncio
async def test_send_gateway_failure_returns_error_dict(hub: NotificationHub) -> None:
    """Сбой Gateway -> error-dict, не исключение."""
    gw = AsyncMock()
    gw.send = AsyncMock(side_effect=RuntimeError("smtp down"))
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        result = await hub.send("email", "user@bank.ru", subject="s", message="m")
    assert result["status"] == "error"
    assert "smtp down" in result["message"]


@pytest.mark.asyncio
async def test_per_channel_methods_map_correctly(hub: NotificationHub) -> None:
    """email/express/webhook/telegram маппятся в send с нужным channel."""
    gw = _gateway_mock()
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        await hub.email("a@b", "s", "m")
        await hub.express("chat-1", "s", "m", is_direct=True)
        await hub.webhook("https://hook", "s", "m", secret="sec")
        await hub.telegram("chat-2", "s", "m")

    channels = [c.kwargs["channel"] for c in gw.send.await_args_list]
    assert channels == ["email", "express", "webhook", "telegram"]
    express_ctx = gw.send.await_args_list[1].kwargs["context"]
    assert express_ctx["is_direct"] is True
    webhook_ctx = gw.send.await_args_list[2].kwargs["context"]
    assert webhook_ctx["secret"] == "sec"


@pytest.mark.asyncio
async def test_express_broadcast_counts_sent(hub: NotificationHub) -> None:
    gw = AsyncMock()
    results_per_call = [SimpleNamespace(status="sent", request_id="r1")]
    gw.send = AsyncMock(side_effect=[SimpleNamespace(status="sent", request_id="r1"), SimpleNamespace(status="failed", request_id="r2")])
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        result = await hub.express_broadcast(["c1", "c2"], "s", "m")
    assert result["status"] == "broadcast"
    assert result["total"] == 2
    assert result["sent"] == 1


@pytest.mark.asyncio
async def test_express_event_formats_emoji_body(hub: NotificationHub) -> None:
    gw = _gateway_mock()
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        await hub.express_event("alert", "chat-1", {"order": 42, "user": "op"})
    ctx = gw.send.await_args.kwargs["context"]
    body = ctx["message"]
    assert ":rotating_light:" in body
    assert "**Alert**" in body
    assert "order" in body and "42" in body


@pytest.mark.asyncio
async def test_broadcast_skips_string_targets(hub: NotificationHub) -> None:
    """channels-элементы-строки пропускаются (контракт требует dict)."""
    gw = _gateway_mock()
    with patch(
        "src.backend.infrastructure.notifications.get_gateway", return_value=gw,
    ):
        result = await hub.broadcast(
            [
                "bare-string",
                {"channel": "email", "to": "a@b"},
            ],
            "s",
            "m",
        )
    assert result["total"] == 2  # считаются ВСЕ targets (контракт)
    assert result["sent"] == 1
    assert gw.send.await_count == 1


# ── _slug контракт ──────────────────────────────────────────────────


def test_slug_transliteration_contracts() -> None:

    assert _slug("КД №12345") == "кд-12345"  # кириллица сохраняется, № удаляется
    assert _slug("Hello, World!") == "hello-world"
    assert _slug("") == "default"
    assert len(_slug("a" * 100)) <= 32
    # docstring-пример "kd-12345" СТАРЫЙ — транслитерации нет (см. B-NEW-6)


# ── NotificationRequest dataclass ───────────────────────────────────


def test_notification_request_defaults() -> None:
    req = NotificationRequest(subject="s", message="m")
    assert req.channel.value == "email"
    assert req.priority == "normal"
    assert req.recipients == []

@pytest.mark.asyncio
async def test_express_create_chat_delegates_to_client(hub: NotificationHub) -> None:
    """197-200: create_chat делегирует в legacy Express client."""
    client = AsyncMock()
    with patch(
        "src.backend.core.di.providers.get_express_client_provider",
        return_value=client,
    ):
        result = await hub.express_create_chat(
            name="chat", members=["u1"], description="d",
        )
    client.create_chat.assert_awaited_once_with(
        name="chat", members=["u1"], description="d", chat_type="group_chat",
    )
    assert result is client.create_chat.return_value
