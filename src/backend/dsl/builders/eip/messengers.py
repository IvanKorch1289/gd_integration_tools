"""Messengers EIP-методы: Express BotX (7) + Telegram Bot API (8).

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.backend.dsl.builders.eip._base import EIPMixinBase

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("MessengersEIPsMixin",)


class MessengersEIPsMixin(EIPMixinBase):
    """Express BotX (7 методов) + Telegram Bot API (8 методов)."""

    # ── Express BotX (Wave 4.2) ──

    def express_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str = "ok",
        silent_response: bool = False,
        sync: bool = False,
        result_property: str = "express_sync_id",
    ) -> "RouteBuilder":
        """Отправить сообщение в Express чат через BotX API."""
        from src.backend.dsl.engine.processors.express import ExpressSendProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressSendProcessor(
                    bot=bot,
                    chat_id_from=chat_id_from,
                    body=body,
                    body_from=body_from,
                    bubble=bubble,
                    keyboard=keyboard,
                    status=status,
                    silent_response=silent_response,
                    sync=sync,
                    result_property=result_property,
                )
            ),
        )

    def express_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_sync_id_from: str = "header.X-Express-Sync-Id",
        chat_id_from: str = "body.group_chat_id",
        body: str | None = None,
        result_property: str = "express_reply_sync_id",
    ) -> "RouteBuilder":
        """Ответить на исходное сообщение Express (reply-thread)."""
        from src.backend.dsl.engine.processors.express import ExpressReplyProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressReplyProcessor(
                    bot=bot,
                    source_sync_id_from=source_sync_id_from,
                    chat_id_from=chat_id_from,
                    body=body,
                    body_from=body_from,
                    result_property=result_property,
                )
            ),
        )

    def express_edit(
        self,
        sync_id_from: str = "properties.express_sync_id",
        *,
        bot: str = "main_bot",
        body: str | None = None,
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str | None = None,
    ) -> "RouteBuilder":
        """Редактировать ранее отправленное Express сообщение."""
        from src.backend.dsl.engine.processors.express import ExpressEditProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressEditProcessor(
                    bot=bot,
                    sync_id_from=sync_id_from,
                    body=body,
                    body_from=body_from,
                    bubble=bubble,
                    keyboard=keyboard,
                    status=status,
                )
            ),
        )

    def express_typing(
        self,
        action: str = "start",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
    ) -> "RouteBuilder":
        """Отправить/остановить индикатор набора в Express чате."""
        from src.backend.dsl.engine.processors.express import ExpressTypingProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressTypingProcessor(
                    bot=bot, chat_id_from=chat_id_from, action=action
                )
            ),
        )

    def express_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        result_property: str = "express_file_sync_id",
    ) -> "RouteBuilder":
        """Отправить файл (S3/LocalFS или exchange-property) в Express чат."""
        from src.backend.dsl.engine.processors.express import ExpressSendFileProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressSendFileProcessor(
                    bot=bot,
                    chat_id_from=chat_id_from,
                    s3_key_from=s3_key_from,
                    file_data_property=file_data_property,
                    file_name=file_name,
                    file_name_from=file_name_from,
                    body=body,
                    body_from=body_from,
                    result_property=result_property,
                )
            ),
        )

    def express_mention(
        self,
        *,
        mention_type: str = "user",
        target_from: str | None = None,
        mention_id: str | None = None,
        name_from: str | None = None,
        property_name: str = "express_mentions",
    ) -> "RouteBuilder":
        """Добавить упоминание (user/chat/channel/contact/all) в exchange-property."""
        from src.backend.dsl.engine.processors.express import ExpressMentionProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressMentionProcessor(
                    mention_type=mention_type,
                    target_from=target_from,
                    mention_id=mention_id,
                    name_from=name_from,
                    property_name=property_name,
                )
            ),
        )

    def express_status(
        self,
        *,
        bot: str = "main_bot",
        sync_id_from: str = "properties.express_sync_id",
        result_property: str = "express_event_status",
    ) -> "RouteBuilder":
        """Запросить статус доставки сообщения по sync_id."""
        from src.backend.dsl.engine.processors.express import ExpressStatusProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExpressStatusProcessor(
                    bot=bot, sync_id_from=sync_id_from, result_property=result_property
                )
            ),
        )

    # ── Telegram Bot API ──

    def telegram_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_keyboard: list[list[str]] | None = None,
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
        result_property: str = "telegram_message_id",
    ) -> "RouteBuilder":
        """Отправить сообщение в Telegram чат через Bot API."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramSendProcessor(
                    bot=bot,
                    chat_id_from=chat_id_from,
                    body=body,
                    body_from=body_from,
                    parse_mode=parse_mode,
                    inline_keyboard=inline_keyboard,
                    reply_keyboard=reply_keyboard,
                    disable_notification=disable_notification,
                    disable_web_page_preview=disable_web_page_preview,
                    result_property=result_property,
                )
            ),
        )

    def telegram_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_message_id_from: str = "body.message.message_id",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        parse_mode: str = "HTML",
        result_property: str = "telegram_reply_message_id",
    ) -> "RouteBuilder":
        """Ответить на сообщение Telegram (reply_to_message_id)."""
        from src.backend.dsl.engine.processors.telegram import TelegramReplyProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramReplyProcessor(
                    bot=bot,
                    source_message_id_from=source_message_id_from,
                    chat_id_from=chat_id_from,
                    body=body,
                    body_from=body_from,
                    parse_mode=parse_mode,
                    result_property=result_property,
                )
            ),
        )

    def telegram_edit(
        self,
        message_id_from: str = "properties.telegram_message_id",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> "RouteBuilder":
        """Редактировать ранее отправленное Telegram-сообщение."""
        from src.backend.dsl.engine.processors.telegram import TelegramEditProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramEditProcessor(
                    bot=bot,
                    chat_id_from=chat_id_from,
                    message_id_from=message_id_from,
                    body=body,
                    body_from=body_from,
                    parse_mode=parse_mode,
                    inline_keyboard=inline_keyboard,
                )
            ),
        )

    def telegram_typing(
        self,
        action: str = "typing",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
    ) -> "RouteBuilder":
        """Отправить chat-action (typing / upload_photo / …) в Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramTypingProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramTypingProcessor(
                    bot=bot, chat_id_from=chat_id_from, action=action
                )
            ),
        )

    def telegram_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        result_property: str = "telegram_file_message_id",
    ) -> "RouteBuilder":
        """Отправить файл (документ) в Telegram чат."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendFileProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramSendFileProcessor(
                    bot=bot,
                    chat_id_from=chat_id_from,
                    s3_key_from=s3_key_from,
                    file_data_property=file_data_property,
                    file_name=file_name,
                    file_name_from=file_name_from,
                    body=body,
                    body_from=body_from,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                    result_property=result_property,
                )
            ),
        )

    def telegram_mention(
        self,
        *,
        user_id_from: str,
        display_name_from: str | None = None,
        parse_mode: str = "MarkdownV2",
        property_name: str = "telegram_mention",
        append: bool = False,
    ) -> "RouteBuilder":
        """Создать фрагмент-упоминание пользователя для вставки в текст."""
        from src.backend.dsl.engine.processors.telegram import TelegramMentionProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramMentionProcessor(
                    user_id_from=user_id_from,
                    display_name_from=display_name_from,
                    parse_mode=parse_mode,
                    property_name=property_name,
                    append=append,
                )
            ),
        )

    def telegram_status(
        self, *, bot: str = "main_bot", result_property: str = "telegram_bot_profile"
    ) -> "RouteBuilder":
        """Запросить профиль бота (getMe) — health-check Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramStatusProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TelegramStatusProcessor(bot=bot, result_property=result_property)
            ),
        )
