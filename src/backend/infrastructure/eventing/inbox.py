"""Inbox — дедупликация входящих событий (ADR-011).

Consumer идемпотентен, если видит повторную публикацию и игнорирует её.
Храним processed event IDs в Redis с TTL; при обработке проверяем
SETNX — если ключ уже существует, это дубликат.
"""

from __future__ import annotations

import logging

__all__ = ("Inbox",)

logger = logging.getLogger("eventing.inbox")


class Inbox:
    """Redis-based dedup для CloudEvents id."""

    def __init__(
        self, *, ttl_seconds: int = 7 * 24 * 3600, prefix: str = "inbox:"
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix

    async def seen_or_mark(self, event_id: str) -> bool:
        """True, если событие уже было обработано (дубликат)."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            logger.debug("Redis недоступен — inbox dedup отключён")
            return False

        key = f"{self.prefix}{event_id}"
        raw = getattr(redis_client, "_raw_client", None) or redis_client

        # SETNX — атомарно: устанавливаем ключ, только если его нет.
        try:
            was_set = await raw.set(key, "1", ex=self.ttl_seconds, nx=True)
        except Exception as exc:
            logger.warning("Inbox Redis fail: %s", exc)
            return False
        return was_set is None or was_set is False
