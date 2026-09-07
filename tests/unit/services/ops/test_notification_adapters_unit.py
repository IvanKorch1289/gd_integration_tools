"""Тесты notification_adapters (T3 ratchet: 0%→≥90%).

Четыре адаптера каналов (email/express/telegram/webhook) под Protocol
NotificationChannel: supports_format, send (success + error->False),
health (success + failure->False).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.ops.notification_adapters import (
    EmailNotificationAdapter,
    ExpressNotificationAdapter,
    NotificationMessage,
    TelegramNotificationAdapter,
    WebhookNotificationAdapter,
)


def _msg(**overrides: object) -> NotificationMessage:
    base: dict[str, object] = {
        "subject": "s",
        "body": "b",
        "recipients": ["r1", "r2"],
        "metadata": {},
    }
    base.update(overrides)
    return NotificationMessage(**base)  # type: ignore[arg-type]


# ── EmailNotificationAdapter ────────────────────────────────────────


def test_email_supports_format() -> None:
    a = EmailNotificationAdapter()
    assert a.channel_name == "email"
    assert a.supports_format("text/plain")
    assert a.supports_format("text/html")
    assert not a.supports_format("application/pdf")


@pytest.mark.asyncio
async def test_email_send_per_recipient() -> None:
    a = EmailNotificationAdapter()
    smtp = AsyncMock()
    smtp.send_email = AsyncMock()
    with patch(
        "src.backend.core.di.providers.get_smtp_client_provider",
        return_value=smtp,
    ):
        assert await a.send(_msg(metadata={"content_type": "text/html"})) is True
    assert smtp.send_email.await_count == 2
    assert smtp.send_email.await_args.kwargs["content_type"] == "text/html"


@pytest.mark.asyncio
async def test_email_send_failure_returns_false() -> None:
    a = EmailNotificationAdapter()
    smtp = AsyncMock()
    smtp.send_email = AsyncMock(side_effect=RuntimeError("smtp down"))
    with patch(
        "src.backend.core.di.providers.get_smtp_client_provider",
        return_value=smtp,
    ):
        assert await a.send(_msg()) is False


@pytest.mark.asyncio
async def test_email_health_true_and_false() -> None:
    a = EmailNotificationAdapter()
    smtp_ok = AsyncMock()
    smtp_ok.test_connection = AsyncMock(return_value=True)
    with patch(
        "src.backend.core.di.providers.get_smtp_client_provider",
        return_value=smtp_ok,
    ):
        assert await a.health() is True

    with patch(
        "src.backend.core.di.providers.get_smtp_client_provider",
        side_effect=RuntimeError("down"),
    ):
        assert await a.health() is False


# ── ExpressNotificationAdapter ──────────────────────────────────────


def test_express_supports_format() -> None:
    a = ExpressNotificationAdapter()
    assert a.channel_name == "express"
    assert a.supports_format("application/json")
    assert not a.supports_format("text/html")


@pytest.mark.asyncio
async def test_express_send_per_recipient() -> None:
    a = ExpressNotificationAdapter()
    client = AsyncMock()
    client.send_message = AsyncMock()
    with patch(
        "src.backend.core.di.providers.get_express_client_provider",
        return_value=client,
    ):
        assert await a.send(_msg()) is True
    assert client.send_message.await_count == 2


@pytest.mark.asyncio
async def test_express_health_ping_and_no_ping() -> None:
    a = ExpressNotificationAdapter()
    with_ping = AsyncMock()
    with_ping.ping = AsyncMock(return_value=True)
    with patch(
        "src.backend.core.di.providers.get_express_client_provider",
        return_value=with_ping,
    ):
        assert await a.health() is True

    without_ping = object()  # нет ping -> True (contract: hasattr-ветка)
    with patch(
        "src.backend.core.di.providers.get_express_client_provider",
        return_value=without_ping,
    ):
        assert await a.health() is True

    with patch(
        "src.backend.core.di.providers.get_express_client_provider",
        side_effect=RuntimeError("down"),
    ):
        assert await a.health() is False


# ── TelegramNotificationAdapter ─────────────────────────────────────


def test_telegram_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    a = TelegramNotificationAdapter()
    assert a._token == "env-token"


def test_telegram_supports_format() -> None:
    a = TelegramNotificationAdapter(bot_token="t")
    assert a.supports_format("text/markdown")
    assert a.supports_format("text/html")
    assert not a.supports_format("application/json")


@pytest.mark.asyncio
async def test_telegram_send_without_token_false() -> None:
    a = TelegramNotificationAdapter(bot_token="")
    assert await a.send(_msg()) is False


@pytest.mark.asyncio
async def test_telegram_send_success_with_parse_mode() -> None:
    a = TelegramNotificationAdapter(bot_token="tok")
    msg = _msg(metadata={"content_type": "text/markdown"})
    client = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    client.post = AsyncMock(return_value=resp)

    with patch(
        "src.backend.core.net.migration_helper.make_http_client"
    ) as mock_client_ctx:
        mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await a.send(msg) is True

    # 2 recipients в _msg -> post на каждого (loop по получателям)
    assert client.post.await_count == 2
    payload = client.post.await_args_list[0].kwargs["json"]
    assert payload["parse_mode"] == "Markdown"
    assert payload["chat_id"] == "r1"
    assert client.post.await_args_list[1].kwargs["json"]["chat_id"] == "r2"


@pytest.mark.asyncio
async def test_telegram_health_no_token_false() -> None:
    a = TelegramNotificationAdapter(bot_token="")
    assert await a.health() is False


@pytest.mark.asyncio
async def test_telegram_health_error_false(monkeypatch: pytest.MonkeyPatch) -> None:
    a = TelegramNotificationAdapter(bot_token="t")
    client = AsyncMock()
    client.get = AsyncMock(side_effect=RuntimeError("net fail"))
    with patch(
        "src.backend.core.net.migration_helper.make_http_client"
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await a.health() is False


# ── WebhookNotificationAdapter ──────────────────────────────────────


def test_webhook_supports_format() -> None:
    a = WebhookNotificationAdapter()
    assert a.channel_name == "webhook"
    assert a.supports_format("application/json")
    assert not a.supports_format("text/markdown")


@pytest.mark.asyncio
async def test_webhook_send_posts_payload_per_url() -> None:
    a = WebhookNotificationAdapter()
    msg = _msg(subject="s", body="b")
    client = AsyncMock()
    resp = MagicMock()
    client.post = AsyncMock(return_value=resp)

    with patch(
        "src.backend.core.net.migration_helper.make_http_client"
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await a.send(msg) is True

    assert client.post.await_count == 2
    payload = client.post.await_args_list[0].kwargs["json"]
    assert payload["subject"] == "s"
    assert payload["body"] == "b"


@pytest.mark.asyncio
async def test_webhook_health_always_true() -> None:
    a = WebhookNotificationAdapter()
    assert await a.health() is True
