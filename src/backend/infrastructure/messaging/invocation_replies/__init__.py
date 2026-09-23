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

from src.backend.infrastructure.messaging.invocation_replies.email import (  # noqa: F401 — re-export
    EmailReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.express import (  # noqa: F401 — re-export
    ExpressReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.memory import (  # noqa: F401 — re-export
    MemoryReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.queue import (  # noqa: F401 — re-export
    QueueReplyChannel,
)
from src.backend.infrastructure.messaging.invocation_replies.registry import (  # noqa: F401 — re-export
    ReplyChannelRegistry,
    get_reply_channel_registry,
)
from src.backend.infrastructure.messaging.invocation_replies.ws import WsReplyChannel

__all__ = (
    "EmailReplyChannel",
    "ExpressReplyChannel",
    "MemoryReplyChannel",
    "QueueReplyChannel",
    "ReplyChannelRegistry",
    "WsReplyChannel",
    "get_reply_channel_registry",
)
