"""Per-tenant quotas — monthly/daily limits поверх Redis."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

__all__ = ("QuotaTracker", "QuotaExceeded")

logger = logging.getLogger("api_mgmt.quotas")


class QuotaExceeded(Exception):
    pass


@dataclass(slots=True)
class QuotaTracker:
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
        try:
            from src.infrastructure.clients.storage.redis import redis_client
        except ImportError:
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
