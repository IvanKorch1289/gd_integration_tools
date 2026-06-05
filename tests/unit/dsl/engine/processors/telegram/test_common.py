"""Unit-тесты для ``src.backend.dsl.engine.processors.telegram._common``."""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tg_module() -> Any:
    from src.backend.dsl.engine.processors.telegram import _common as mod

    return mod


@pytest.mark.unit
class TestGetTelegramClient:
    def test_get_telegram_client_raises_when_disabled(
        self, tg_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = SimpleNamespace(
            enabled=False,
            bot_id="1",
            secret_key="s",
            base_url="https://api.telegram.org",
        )
        monkeypatch.setattr(
            "src.backend.core.config.telegram.telegram_bot_settings", settings
        )

        with pytest.raises(RuntimeError, match="Telegram интеграция отключена"):
            tg_module.get_telegram_client()

    def test_get_telegram_client_raises_for_unknown_bot(
        self, tg_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = SimpleNamespace(
            enabled=True,
            bot_id="1",
            secret_key="s",
            base_url="https://api.telegram.org",
        )
        monkeypatch.setattr(
            "src.backend.core.config.telegram.telegram_bot_settings", settings
        )

        with pytest.raises(RuntimeError, match="Multi-bot пока не реализован"):
            tg_module.get_telegram_client("extra_bot")

    def test_get_telegram_client_returns_main_bot_client(
        self, tg_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = SimpleNamespace(
            enabled=True,
            bot_id="42",
            secret_key="secret",
            base_url="https://tg.example",
        )
        monkeypatch.setattr(
            "src.backend.core.config.telegram.telegram_bot_settings", settings
        )

        fake_config_cls = MagicMock()
        fake_client_cls = MagicMock()
        monkeypatch.setattr(
            "src.backend.infrastructure.clients.external.telegram_bot.TelegramBotConfig",
            fake_config_cls,
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.clients.external.telegram_bot.TelegramBotClient",
            fake_client_cls,
        )

        client = tg_module.get_telegram_client()

        fake_config_cls.assert_called_once_with(
            bot_id="42", secret_key="secret", base_url="https://tg.example"
        )
        fake_client_cls.assert_called_once_with(fake_config_cls.return_value)
        assert client is fake_client_cls.return_value


@pytest.mark.unit
class TestResolveValueReExport:
    def test_resolve_value_accessible_from_telegram_common(
        self, tg_module: Any
    ) -> None:
        # Убеждаемся, что re-export ``resolve_value`` доступен.
        assert callable(tg_module.resolve_value)
