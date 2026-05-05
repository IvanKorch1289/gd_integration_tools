"""Backends для :class:`InvocationReplyChannel` (W22.3 + Этап B).

* :class:`MemoryReplyChannel` — in-memory polling, для dev_light/тестов.
* :class:`WsReplyChannel` — push через активные WebSocket-соединения.
* :class:`EmailReplyChannel` — push через SMTP (EmailAdapter).
* :class:`ExpressReplyChannel` — push в Express чат (ExpressAdapter).
* :class:`QueueReplyChannel` — publish в Redis/Rabbit/Kafka (StreamClient).

Все backends регистрируются в :class:`ReplyChannelRegistry`. Получение
сингл-инстанса — через :func:`get_reply_channel_registry`.
"""

from __future__ import annotations

from src.backend.infrastructure.messaging.invocation_replies.email import (
    EmailReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.express import (
    ExpressReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.memory import (
    MemoryReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.queue import (
    QueueReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.registry import (
    ReplyChannelRegistry,
    get_reply_channel_registry,
)
from src.backend.infrastructure.messaging.invocation_replies.ws import WsReplyChannel

__all__ = (
    "MemoryReplyChannel",
    "WsReplyChannel",
    "EmailReplyChannel",
    "ExpressReplyChannel",
    "QueueReplyChannel",
    "ReplyChannelRegistry",
    "get_reply_channel_registry",
)
