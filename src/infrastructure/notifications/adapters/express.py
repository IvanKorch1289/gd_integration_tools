"""Express NotificationChannel — уведомления через корпоративный мессенджер.

Реализует протокол :class:`NotificationChannel` для Express BotX.
Отправляет уведомления через :class:`ExpressBotClient`.

Поддержка:
- Текстовые уведомления (body, subject → `<b>subject</b>\\n\\nbody`).
- Bubble-кнопки через ``metadata["bubble"]`` (быстрые действия).
- Упоминания пользователей через ``metadata["mentions"]``.
- Произвольный bot через ``metadata["bot"]`` (default ``main_bot``).

recipient = ``group_chat_id`` (UUID чата Express) или ``user_huid``
если ``metadata["mode"] == "personal"`` — в этом случае создаётся 1-1 чат.
"""

from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.notifications.adapters.base import NotificationChannel

__all__ = ("ExpressAdapter",)

_logger = logging.getLogger("notifications.express")


class ExpressAdapter:
    """Express channel-adapter для NotificationGateway."""

    kind = "express"

    def __init__(self, *, default_bot: str = "main_bot") -> None:
        self._default_bot = default_bot

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправить уведомление в Express чат.

        Args:
            recipient: ``group_chat_id`` (UUID).
            subject: Заголовок (выводится жирным).
            body: Тело сообщения.
            metadata: ``{bot?, bubble?, keyboard?, mentions?, status?}``.

        Raises:
            RuntimeError: Если Express отключён или BotX недоступен.
        """
        from src.dsl.engine.processors.express._common import get_express_client
        from src.infrastructure.clients.external.express_bot import (
            BotxButton,
            BotxMention,
            BotxMessage,
        )

        bot_name = str(metadata.get("bot") or self._default_bot)
        text = f"**{subject}**\n\n{body}" if subject else body

        bubble_btns = [
            [BotxButton(**btn) for btn in row] for row in (metadata.get("bubble") or [])
        ]
        keyboard_btns = [
            [BotxButton(**btn) for btn in row]
            for row in (metadata.get("keyboard") or [])
        ]
        mentions = [BotxMention(**m) for m in (metadata.get("mentions") or [])]

        msg = BotxMessage(
            group_chat_id=recipient,
            body=text,
            status=str(metadata.get("status") or "ok"),
            bubble=bubble_btns,
            keyboard=keyboard_btns,
            mentions=mentions,
        )

        client = get_express_client(bot_name)
        async with client:
            sync_id = await client.send_message(msg)
        _logger.debug(
            "ExpressAdapter: sent recipient=%s subject=%r sync_id=%s",
            recipient,
            subject,
            sync_id,
        )

    async def health(self) -> bool:
        """Проверка доступности Express интеграции."""
        try:
            from src.core.config.express_settings import express_settings

            return bool(express_settings.enabled and express_settings.bot_id)
        except Exception:  # noqa: BLE001
            return False


# Compile-time проверка соответствия протоколу.
assert isinstance(ExpressAdapter(), NotificationChannel)  # noqa: S101
