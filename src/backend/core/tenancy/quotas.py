"""Per-tenant quotas — monthly/daily limits поверх Redis."""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.backend.core.logging import get_logger

__all__ = ("QuotaExceeded", "QuotaTracker")

logger = get_logger("api_mgmt.quotas")


class QuotaExceeded(Exception):
    """Исключение: тенант превысил квоту ``limit`` в окне ``period_seconds``.

    Raises:
        QuotaExceeded: при попытке consume сверх установленного лимита.
            Сообщение содержит ``tenant_id``, ``resource`` и текущие
            ``current/limit`` для observability.
    """


@dataclass(slots=True)
class QuotaTracker:
    """Sliding-window counter для rate-limit'ов тенанта поверх Redis.

    Attributes:
        prefix: Префикс ключей в Redis; используется для namespacing
            разных окружений (например ``quota:`` или ``quota_staging:``).
    """

    prefix: str = "quota:"

    async def consume(
        self,
        tenant_id: str,
        resource: str,
        units: int = 1,
        *,
        limit: int,
        period_seconds: int,
    ) -> dict:
        """Атомарно списать ``units`` из квоты ``resource`` для ``tenant_id``.

        Использует Redis ``INCRBY`` + ``EXPIRE``. При недоступности Redis
        возвращает ``{"remaining": limit, ...}`` (fail-open режим) и
        логирует warning.

        Args:
            tenant_id: Идентификатор тенанта.
            resource: Имя ресурса/эндпоинта (например ``messages.send``).
            units: Количество единиц, списываемых за одну операцию.
            limit: Максимум единиц в одном окне.
            period_seconds: Длина окна (1 минута, 1 час, 1 день...).

        Returns:
            Словарь с ключами ``remaining``, ``limit``, ``reset_at``
            (UTC timestamp начала следующего окна).

        Raises:
            QuotaExceeded: если после инкремента счётчик превысил ``limit``.
        """
        # S162 W4: use module-attr lookup (not local binding) so that
        # monkeypatching storage.redis.get_redis_client in tests takes
        # effect. Was 'from ... import get_redis_client as redis_client'
        # which used local binding and ignored patches.
        # Per pattern #11 (S157 W2 fix).
        from src.backend.infrastructure.clients.storage import redis as _redis_mod

        try:
            redis_client = _redis_mod.get_redis_client()
        except ImportError, AttributeError:
            return {"remaining": limit, "limit": limit, "reset_at": 0}

        now = int(time.time())
        window_start = now - (now % period_seconds)
        key = f"{self.prefix}{tenant_id}:{resource}:{window_start}"
        raw = getattr(redis_client, "_raw_client", None) or redis_client
        try:
            current = await raw.incrby(key, units)
            await raw.expire(key, period_seconds)
        except Exception as exc:
            logger.warning("Quota Redis fail (fail-open): %s", exc)
            return {"remaining": limit - units, "limit": limit, "reset_at": 0}
        if current > limit:
            raise QuotaExceeded(f"{tenant_id}:{resource}: {current}/{limit} in window")
        return {
            "remaining": max(0, limit - current),
            "limit": limit,
            "reset_at": window_start + period_seconds,
        }
