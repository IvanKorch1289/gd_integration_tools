"""Inbox — дедупликация входящих событий (ADR-011).

Consumer идемпотентен, если видит повторную публикацию и игнорирует её.
Храним processed event IDs в Redis с TTL; при обработке проверяем
SETNX — если ключ уже существует, это дубликат.

Sprint 8 K2 W4 — добавлен ``fail_mode`` параметр:

* ``"open"`` (default, backwards-compatible): при недоступности Redis
  пропускает событие как новое (риск дубликата, низкий impact).
* ``"closed"``: при недоступности Redis выбрасывает
  :class:`InboxUnavailableError` — caller должен вернуть 503 и
  отказаться обрабатывать событие до восстановления Redis. Используется
  для критичных операций (платежи, RPA-команды), где дубликат опаснее
  задержки.
"""

from __future__ import annotations

from typing import Literal

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("Inbox", "InboxFailMode", "InboxUnavailableError")

logger = get_logger("eventing.inbox")

InboxFailMode = Literal["open", "closed"]


class InboxUnavailableError(RuntimeError):
    """Поднимается, когда Redis недоступен в fail-mode=closed."""


class Inbox:
    """Redis-based dedup для CloudEvents id.

    Args:
        ttl_seconds: Время жизни ключа дедупликации (default 7 дней).
        prefix: Префикс ключей в Redis.
        fail_mode: Поведение при недоступности Redis:
          ``"open"`` (default) — пропускает событие; ``"closed"`` —
          выбрасывает :class:`InboxUnavailableError` (caller отдаёт 503).
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 7 * 24 * 3600,
        prefix: str = "inbox:",
        fail_mode: InboxFailMode = "open",
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix
        self.fail_mode: InboxFailMode = fail_mode

    async def seen_or_mark(self, event_id: str) -> bool:
        """True, если событие уже было обработано (дубликат).

        Raises:
            InboxUnavailableError: Если Redis недоступен и
                ``fail_mode="closed"``.
        """
        try:
            from src.backend.infrastructure.clients.storage.redis import get_redis_client as redis_client
        except ImportError as exc:
            if self.fail_mode == "closed":
                raise InboxUnavailableError(
                    "Redis client unavailable; fail_mode=closed"
                ) from exc
            logger.debug("Redis недоступен — inbox dedup отключён")
            return False

        key = f"{self.prefix}{event_id}"
        raw = getattr(redis_client, "_raw_client", None) or redis_client

        # SETNX — атомарно: устанавливаем ключ, только если его нет.
        try:
            was_set = await raw.set(key, "1", ex=self.ttl_seconds, nx=True)
        except Exception as exc:
            if self.fail_mode == "closed":
                raise InboxUnavailableError(f"Redis SETNX failed: {exc}") from exc
            logger.warning("Inbox Redis fail: %s", exc)
            return False
        return was_set is None or was_set is False
