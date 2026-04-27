"""Общие утилиты Express DSL-процессоров.

Содержит:
- ``resolve_value`` — извлечение значения из exchange по точечному пути.
- ``get_express_client`` — фабрика клиента по имени бота.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.dsl.engine.exchange import Exchange
    from src.infrastructure.clients.external.express_bot import ExpressBotClient

__all__ = ("resolve_value", "get_express_client")


def _walk_path(node: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def resolve_value(exchange: Exchange[Any], expression: str) -> Any:
    """Извлекает значение из exchange по выражению вида ``namespace.path.to.field``.

    Поддерживаемые namespaces:
        ``body``        — exchange.in_message.body
        ``header.<key>`` — exchange.in_message.headers[<key>]
        ``properties``  — exchange.properties
        ``result``      — exchange.properties["action_result"]
    """
    if expression.startswith("header."):
        return exchange.in_message.headers.get(expression.removeprefix("header."))
    parts = expression.split(".")
    head, tail = parts[0], parts[1:]
    if head == "body":
        return _walk_path(exchange.in_message.body, tail)
    if head == "properties":
        if not tail:
            return exchange.properties
        return _walk_path(exchange.properties, tail)
    if head == "result":
        result = exchange.get_property("action_result")
        return _walk_path(result, tail) if tail else result
    # fallback: по properties
    return _walk_path(exchange.properties, parts)


def get_express_client(bot_name: str = "main_bot") -> ExpressBotClient:
    """Возвращает ``ExpressBotClient`` для указанного бота.

    Args:
        bot_name: Имя бота из настроек. ``main_bot`` → основной бот из
            ``express_settings``. Иначе — ищется в ``express_settings.extra_bots``.

    Raises:
        RuntimeError: Если бот не найден или Express отключён.
    """
    from src.core.config.express_settings import express_settings
    from src.infrastructure.clients.external.express_bot import (
        BotConfig,
        ExpressBotClient,
    )

    if not express_settings.enabled:
        raise RuntimeError(
            "Express интеграция отключена (express_settings.enabled=False)"
        )

    if bot_name == "main_bot":
        host = express_settings.botx_host or _host_from_url(express_settings.botx_url)
        config = BotConfig(
            bot_id=express_settings.bot_id,
            secret_key=express_settings.secret_key,
            botx_host=host,
            base_url=express_settings.botx_url,
        )
        return ExpressBotClient(config)

    for bot in express_settings.extra_bots:
        if bot.get("name") == bot_name:
            return ExpressBotClient(
                BotConfig(
                    bot_id=str(bot["bot_id"]),
                    secret_key=str(bot["secret_key"]),
                    botx_host=str(
                        bot.get("botx_host") or _host_from_url(str(bot["base_url"]))
                    ),
                    base_url=str(bot["base_url"]),
                )
            )

    raise RuntimeError(f"Express бот {bot_name!r} не найден в настройках")


def _host_from_url(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
