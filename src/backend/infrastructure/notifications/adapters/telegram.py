"""Telegram NotificationChannel — уведомления через Telegram Bot API.

Реализует протокол :class:`NotificationChannel` для Telegram. С W15.3
делегирует отправку в :class:`TelegramBotClient` (httpx, единый
bot-channel контракт BaseBotChannelSettings — Express/Telegram).

Конструктор поддерживает два режима:

1. **Через settings (рекомендуется)** —
   ``TelegramAdapter(default_bot="main_bot")``: читает токен и base_url
   из ``telegram_bot_settings`` (W15.2). Health учитывает
   ``telegram_bot_settings.enabled``.

2. **Через callable-провайдер (legacy IL2.2)** —
   ``TelegramAdapter(bot_token_provider=lambda: token, ...)``: токен
   ``{bot_id}:{secret_key}`` поставляется внешним замыканием
   (например, из Vault). Сохранён для обратной совместимости.

Поддержка metadata:
- ``parse_mode`` (HTML / MarkdownV2 / Markdown) — default ``HTML``.
- ``inline_keyboard`` — 2D массив ``{text, url|callback_data, ...}``.
- ``reply_keyboard`` — 2D массив строк.
- ``silent`` — bool, отправка без звука (``disable_notification``).
- ``disable_web_page_preview`` — bool.

recipient = ``chat_id`` (числовой ID или ``@channelname``).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.backend.infrastructure.notifications.adapters.base import NotificationChannel

__all__ = ("TelegramAdapter",)

_logger = logging.getLogger("notifications.telegram")


class TelegramAdapter:
    """Telegram channel-adapter для NotificationGateway."""

    kind = "telegram"

    def __init__(
        self,
        *,
        bot_token_provider: Callable[[], str] | None = None,
        default_bot: str = "main_bot",
        upstream_name: str = "telegram-api",
        parse_mode: str = "HTML",
    ) -> None:
        """
        Args:
            bot_token_provider: Legacy callable, возвращающий токен
                ``{bot_id}:{secret_key}``. Если задан — используется
                вместо ``telegram_bot_settings``.
            default_bot: Имя бота из ``telegram_bot_settings`` (W15.2).
                Используется когда ``bot_token_provider`` не задан.
            upstream_name: Имя HTTP upstream-профиля (зарезервировано
                для совместимости IL2.2; в W15.3 не используется).
            parse_mode: Режим разметки текста по умолчанию.
        """
        self._bot_token_provider = bot_token_provider
        self._default_bot = default_bot
        self._upstream_name = upstream_name
        self._default_parse_mode = parse_mode

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправляет уведомление в Telegram чат.

        Args:
            recipient: ``chat_id`` (числовой ID или ``@channelname``).
            subject: Заголовок (выводится жирным в HTML / MarkdownV2).
            body: Тело сообщения.
            metadata: ``{parse_mode?, inline_keyboard?, reply_keyboard?,
                silent?, disable_web_page_preview?, bot?}``.

        Raises:
            RuntimeError: Если Telegram отключён или токен пуст.
            httpx.HTTPStatusError: При HTTP-ошибке Bot API.
        """
        from src.backend.infrastructure.clients.external.telegram_bot import (
            TelegramBotClient,
            TelegramButton,
            TelegramMessage,
        )

        parse_mode = str(metadata.get("parse_mode") or self._default_parse_mode)
        text = self._format_text(subject, body, parse_mode)

        inline = [
            [TelegramButton(**self._normalize_btn(btn)) for btn in row]
            for row in (metadata.get("inline_keyboard") or [])
        ]
        reply: list[list[str]] = list(metadata.get("reply_keyboard") or [])

        msg = TelegramMessage(
            chat_id=recipient,
            text=text,
            parse_mode=parse_mode,
            inline_keyboard=inline,
            reply_keyboard=reply,
            disable_notification=bool(metadata.get("silent", False)),
            disable_web_page_preview=bool(
                metadata.get("disable_web_page_preview", False)
            ),
        )

        config = self._build_config()
        client = TelegramBotClient(config)
        async with client:
            message_id = await client.send_message(msg)
        _logger.debug(
            "TelegramAdapter: recipient=%s subject=%r message_id=%s",
            recipient,
            subject,
            message_id,
        )

    async def health(self) -> bool:
        """Проверка доступности Telegram интеграции."""
        if self._bot_token_provider is not None:
            try:
                return bool(self._bot_token_provider())
            except Exception:  # noqa: BLE001
                return False
        try:
            from src.backend.core.config.telegram import telegram_bot_settings

            return bool(telegram_bot_settings.enabled and telegram_bot_settings.bot_id)
        except Exception:  # noqa: BLE001
            return False

    def _build_config(self) -> Any:
        """Собирает ``TelegramBotConfig`` из callable-провайдера или settings."""
        from src.backend.infrastructure.clients.external.telegram_bot import (
            TelegramBotConfig,
        )

        if self._bot_token_provider is not None:
            token = self._bot_token_provider()
            if not token:
                raise RuntimeError("Telegram bot token missing")
            bot_id, _, secret_key = token.partition(":")
            return TelegramBotConfig(bot_id=bot_id, secret_key=secret_key)

        from src.backend.core.config.telegram import telegram_bot_settings

        if not telegram_bot_settings.enabled:
            raise RuntimeError(
                "Telegram интеграция отключена (telegram_bot_settings.enabled=False)"
            )
        return TelegramBotConfig(
            bot_id=telegram_bot_settings.bot_id,
            secret_key=telegram_bot_settings.secret_key,
            base_url=telegram_bot_settings.base_url,
        )

    @staticmethod
    def _format_text(subject: str, body: str, parse_mode: str) -> str:
        """Собирает текст сообщения с заголовком в зависимости от parse_mode."""
        if not subject:
            return body
        if parse_mode == "HTML":
            return f"<b>{_html_escape(subject)}</b>\n\n{body}"
        if parse_mode in {"MarkdownV2", "Markdown"}:
            return f"*{subject}*\n\n{body}"
        return f"{subject}\n\n{body}"

    @staticmethod
    def _normalize_btn(raw: dict[str, Any]) -> dict[str, Any]:
        """Приводит dict-описание кнопки к kwargs TelegramButton."""
        allowed = {"text", "url", "callback_data", "switch_inline_query", "web_app_url"}
        return {k: v for k, v in raw.items() if k in allowed}


def _html_escape(text: str) -> str:
    """Минимальное HTML-экранирование для Telegram parse_mode=HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Compile-time проверка соответствия протоколу.
assert isinstance(TelegramAdapter(bot_token_provider=lambda: ""), NotificationChannel)  # noqa: S101
