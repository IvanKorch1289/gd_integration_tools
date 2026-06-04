"""Tests for src.backend.core.config.telegram."""

from __future__ import annotations

from src.backend.core.config.telegram import TelegramBotSettings


class TestTelegramBotSettings:
    def test_defaults(self) -> None:
        s = TelegramBotSettings()
        assert s.base_url == "https://api.telegram.org"
        assert s.parse_mode == "HTML"
        assert s.polling_mode is False
        assert s.disable_notification is False

    def test_token_empty_when_no_credentials(self) -> None:
        s = TelegramBotSettings()
        assert s.token == ""

    def test_token_format(self) -> None:
        s = TelegramBotSettings(bot_id="123", secret_key="abc")
        assert s.token == "123:abc"
