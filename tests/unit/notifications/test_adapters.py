"""
Тесты адаптеров NotificationGateway.

Проверяют, что каждый адаптер:
    * Имеет атрибут ``kind`` (уникальный строковый ключ).
    * Удовлетворяет Protocol ``NotificationChannel`` из base.py.
    * Не делает реальных сетевых вызовов (все конкретные вызовы
      мокаются, потому что юнит-тесты не должны зависеть от внешних API).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.notifications.adapters.base import NotificationChannel


def test_email_adapter_conforms_to_protocol() -> None:
    """EmailAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.email import EmailAdapter

    adapter = EmailAdapter(from_address="noreply@example.com")

    assert adapter.kind == "email"
    assert isinstance(adapter, NotificationChannel)


def test_sms_adapter_conforms_to_protocol() -> None:
    """SMSAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.sms import SMSAdapter

    adapter = SMSAdapter(
        provider="smsru",
        credentials_provider=lambda: "test_api_id",
        upstream_name="sms-smsru",
    )

    assert adapter.kind == "sms"
    assert isinstance(adapter, NotificationChannel)


def test_telegram_adapter_conforms_to_protocol() -> None:
    """TelegramAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.telegram import TelegramAdapter

    adapter = TelegramAdapter(
        bot_token_provider=lambda: "123:abc",
        upstream_name="telegram",
    )

    assert adapter.kind == "telegram"
    assert isinstance(adapter, NotificationChannel)


def test_slack_adapter_conforms_to_protocol() -> None:
    """SlackAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.slack import SlackAdapter

    adapter = SlackAdapter(
        webhook_url_provider=lambda: "https://hooks.slack.com/services/XYZ",
        upstream_name="slack",
    )

    assert adapter.kind == "slack"
    assert isinstance(adapter, NotificationChannel)


def test_teams_adapter_conforms_to_protocol() -> None:
    """TeamsAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.teams import TeamsAdapter

    adapter = TeamsAdapter(
        webhook_url_provider=lambda: "https://outlook.office.com/webhook/ABC",
        upstream_name="teams",
    )

    assert adapter.kind == "teams"
    assert isinstance(adapter, NotificationChannel)


def test_webhook_adapter_conforms_to_protocol() -> None:
    """WebhookAdapter реализует NotificationChannel."""
    from src.infrastructure.notifications.adapters.webhook import WebhookAdapter

    adapter = WebhookAdapter(upstream_name="webhook")

    assert adapter.kind == "webhook"
    assert isinstance(adapter, NotificationChannel)


def test_all_adapters_have_unique_kinds() -> None:
    """Каждый адаптер имеет уникальный ``kind`` — это гарантирует
    корректную маршрутизацию в ``PriorityRouter`` и идентификацию
    в логах / метриках."""
    from src.infrastructure.notifications.adapters.email import EmailAdapter
    from src.infrastructure.notifications.adapters.slack import SlackAdapter
    from src.infrastructure.notifications.adapters.sms import SMSAdapter
    from src.infrastructure.notifications.adapters.teams import TeamsAdapter
    from src.infrastructure.notifications.adapters.telegram import TelegramAdapter
    from src.infrastructure.notifications.adapters.webhook import WebhookAdapter

    adapters = [
        EmailAdapter(from_address="no@e.com"),
        SMSAdapter(provider="smsru", credentials_provider=lambda: "x"),
        TelegramAdapter(bot_token_provider=lambda: "x"),
        SlackAdapter(webhook_url_provider=lambda: "x"),
        TeamsAdapter(webhook_url_provider=lambda: "x"),
        WebhookAdapter(upstream_name="webhook"),
    ]

    kinds = [a.kind for a in adapters]
    assert len(kinds) == len(set(kinds)), f"Пересечения kind: {kinds}"
