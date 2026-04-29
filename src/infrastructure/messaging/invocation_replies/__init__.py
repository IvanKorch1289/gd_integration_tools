"""Backends для :class:`InvocationReplyChannel` (W22.3).

* :class:`MemoryReplyChannel` — in-memory polling, для dev_light/тестов.
* :class:`WsReplyChannel` — push через активные WebSocket-соединения.

Все backends регистрируются в :class:`ReplyChannelRegistry`. Получение
сингл-инстанса — через :func:`get_reply_channel_registry`.
"""

from __future__ import annotations

from src.infrastructure.messaging.invocation_replies.memory import MemoryReplyChannel
from src.infrastructure.messaging.invocation_replies.registry import (
    ReplyChannelRegistry,
    get_reply_channel_registry,
)
from src.infrastructure.messaging.invocation_replies.ws import WsReplyChannel

__all__ = (
    "MemoryReplyChannel",
    "WsReplyChannel",
    "ReplyChannelRegistry",
    "get_reply_channel_registry",
)
