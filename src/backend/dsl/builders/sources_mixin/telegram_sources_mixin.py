"""S97 W4 — Telegram Bot webhook source registration.

Добавляет ``from_telegram`` метод в RouteBuilder — обёртка над
:class:`TelegramWebhookSource` для регистрации Telegram webhook в DSL route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class TelegramSourcesMixin:
    """Telegram Bot webhook source registration для RouteBuilder.

    Позволяет регистрировать Telegram Bot webhook как DSL route source.
    Каждый incoming update эмитится как DSL message.
    """

    __slots__ = ()

    @classmethod
    def from_telegram(
        cls,
        route_id: str,
        bot_token: str,
        *,
        secret_token: str | None = None,
        allowed_updates: tuple[str, ...] | None = None,
        offset: int = 0,
    ) -> RouteBuilder:
        """Telegram Bot webhook: регистрирует маршрут с Telegram-источником.

        S97 W4: использует :class:`TelegramWebhookSource` для Bot API
        webhook consumer. Каждое incoming update эмитится как DSL message.

        Args:
            route_id: Уникальный ID маршрута.
            bot_token: Telegram Bot API token (от @BotFather).
            secret_token: optional X-Telegram-Bot-Api-Secret-Token (HMAC validation).
            allowed_updates: tuple of update types (default: ``("message",)``).
            offset: initial update_id offset (для resume).

        Returns:
            RouteBuilder с source ``telegram:<route_id>``.

        Example::

            route = (
                RouteBuilder.from_telegram(
                    "support_bot",
                    bot_token="...",
                    secret_token="...",
                    allowed_updates=("message", "callback_query"),
                )
                .transform(parse_command)
                .dispatch_action("support.handle")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module(
            "src.backend.infrastructure.sources.telegram_webhook"
        )
        source = mod.TelegramWebhookSource(
            bot_token=bot_token,
            secret_token=secret_token,
            allowed_updates=allowed_updates or ("message",),
            offset=offset,
        )
        builder = cls.from_(  # type: ignore[return-value]
            route_id,
            source=f"telegram:{route_id}",
            description=f"Telegram Bot: {bot_token[:8]}...",
        )
        object.__setattr__(builder, "_telegram_source", source)
        return builder
