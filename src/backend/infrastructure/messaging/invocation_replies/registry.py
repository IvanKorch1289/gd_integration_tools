"""Registry активных :class:`InvocationReplyChannel` (W22.3).

Singleton, в котором хранится по одному backend на :class:`ReplyChannelKind`.
Получение через :func:`get_reply_channel_registry`. По умолчанию
регистрирует :class:`MemoryReplyChannel` (kind ``api``) и
:class:`WsReplyChannel` (kind ``ws``).
"""

from __future__ import annotations

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)

__all__ = ("ReplyChannelRegistry", "get_reply_channel_registry")


class ReplyChannelRegistry:
    """Хранит и предоставляет :class:`InvocationReplyChannel` по типу."""

    def __init__(self) -> None:
        self._channels: dict[ReplyChannelKind, InvocationReplyChannel] = {}

    def register(self, channel: InvocationReplyChannel) -> None:
        """Регистрирует backend; перезаписывает уже существующий той же kind."""
        self._channels[channel.kind] = channel

    def get(self, kind: ReplyChannelKind | str) -> InvocationReplyChannel | None:
        """Возвращает backend по типу; ``None`` — если не зарегистрирован."""
        if isinstance(kind, str):
            try:
                kind = ReplyChannelKind(kind)
            except ValueError:
                return None
        return self._channels.get(kind)

    def kinds(self) -> tuple[ReplyChannelKind, ...]:
        """Перечисляет зарегистрированные kinds (для introspection)."""
        return tuple(self._channels.keys())


_registry_singleton: ReplyChannelRegistry | None = None


def get_reply_channel_registry() -> ReplyChannelRegistry:
    """Singleton :class:`ReplyChannelRegistry` с дефолтными backends.

    Lazy-инициализация: при первом вызове регистрирует все пять backend'ов
    (``api``, ``ws``, ``email``, ``express``, ``queue``). Push-only каналы
    (email/express/queue) при отсутствии конфигурации (recipient/topic в
    ``response.metadata``) корректно пропускают доставку с warning, поэтому
    их безопасно регистрировать всегда — даже в dev_light без SMTP/MQ.
    Перерегистрация поверх singleton разрешена через ``register`` — это
    используется в тестах.
    """
    global _registry_singleton
    if _registry_singleton is None:
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
        from src.backend.infrastructure.messaging.invocation_replies.ws import (
            WsReplyChannel,
        )

        registry = ReplyChannelRegistry()
        registry.register(MemoryReplyChannel())
        registry.register(WsReplyChannel())
        registry.register(EmailReplyChannel())
        registry.register(ExpressReplyChannel())
        registry.register(QueueReplyChannel())
        _registry_singleton = registry
    return _registry_singleton
