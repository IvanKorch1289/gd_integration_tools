r"""Express NotificationChannel — уведомления через корпоративный мессенджер.

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

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.notifications.adapters.base import NotificationChannel

__all__ = ("ExpressAdapter",)

_logger = get_logger("notifications.express")


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
        from src.backend.infrastructure.clients.external.express_bot import (
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

        # Sprint 37 W1 (Phase B Item 5, ADR-0282 §3): inline client factory
        # directly (no DSL bridge — `infrastructure→infrastructure` allowed).
        # Previously: `from src.backend.dsl.engine.processors.express._common
        # import get_express_client` (1 cross-layer entry in allowlist).
        from src.backend.infrastructure.clients.external.express_bot import (
            BotConfig,
            ExpressBotClient,
        )

        from src.backend.core.config.express import express_settings

        if not express_settings.enabled:
            raise RuntimeError(
                "Express интеграция отключена (express_settings.enabled=False)"
            )

        if bot_name == "main_bot":
            host = express_settings.botx_host or _host_from_url(
                express_settings.botx_url
            )
            config = BotConfig(
                bot_id=express_settings.bot_id,
                secret_key=express_settings.secret_key,
                botx_host=host,
                base_url=express_settings.botx_url,
            )
        else:
            # Look up extra_bots
            config = None
            for bot in express_settings.extra_bots:
                if bot.get("name") == bot_name:
                    config = BotConfig(
                        bot_id=str(bot["bot_id"]),
                        secret_key=str(bot["secret_key"]),
                        botx_host=str(
                            bot.get("botx_host") or _host_from_url(str(bot["base_url"]))
                        ),
                        base_url=str(bot["base_url"]),
                    )
                    break
            if config is None:
                raise RuntimeError(f"Express бот {bot_name!r} не найден в настройках")

        client = ExpressBotClient(config)
        async with client:
            sync_id = await client.send_message(msg)
        _logger.debug(
            "ExpressAdapter: sent recipient=%s subject=%r sync_id=%s",
            recipient,
            subject,
            sync_id,
        )

    async def health(self, mode: str = "fast") -> HealthResult:
        """Проверка доступности Express интеграции."""
        import time

        start = time.perf_counter()
        try:
            from src.backend.core.config.express import express_settings

            ok = bool(express_settings.enabled and express_settings.bot_id)
            latency_ms = (time.perf_counter() - start) * 1000.0
            if ok:
                return HealthResult.ok(latency_ms=latency_ms, mode=mode)
            return HealthResult.failed(
                error="Express integration disabled or bot_id missing",
                mode=mode,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )


def _host_from_url(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


# Compile-time проверка соответствия протоколу.
assert isinstance(ExpressAdapter(), NotificationChannel)  # nosec
