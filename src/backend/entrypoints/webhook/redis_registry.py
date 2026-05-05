"""Redis-backed webhook subscription registry (multi-instance safe).

Заменяет in-memory registry.py для N-инстанс deployment.
Все подписки хранятся в Redis HASH, cache per-instance 60s.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from src.backend.core.di.providers import (
    get_redis_hash_factory_provider,
    get_redis_pubsub_factory_provider,
)

__all__ = ("WebhookSubscription", "RedisWebhookRegistry", "redis_webhook_registry")

logger = logging.getLogger("entrypoints.webhook.redis_registry")


@dataclass
class WebhookSubscription:
    """Webhook subscription (совместимо с in-memory registry)."""

    event_type: str
    target_url: str
    secret: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    active: bool = True


class RedisWebhookRegistry:
    """Redis-backed webhook registry с локальным кешем (60s TTL).

    Multi-instance: все инстансы видят одни и те же subscriptions.
    Pub/sub notify при изменениях для invalidation локальных кешей.
    """

    def __init__(self) -> None:
        redis_hash_cls = get_redis_hash_factory_provider()
        redis_pubsub_cls = get_redis_pubsub_factory_provider()
        self._store = redis_hash_cls("webhook:subs")
        self._invalidation = redis_pubsub_cls("webhook:subs:invalidate")
        self._cache: dict[str, WebhookSubscription] = {}
        self._cache_updated: float = 0
        self._cache_ttl = 60.0

    async def add(self, sub: WebhookSubscription) -> WebhookSubscription:
        await self._store.set(sub.id, asdict(sub))
        await self._invalidation.publish({"action": "add", "id": sub.id})
        self._cache[sub.id] = sub
        return sub

    async def remove(self, sub_id: str) -> bool:
        removed = await self._store.delete(sub_id)
        if not removed:
            raise KeyError(f"Webhook subscription '{sub_id}' not found")
        await self._invalidation.publish({"action": "remove", "id": sub_id})
        self._cache.pop(sub_id, None)
        return True

    async def get(self, sub_id: str) -> WebhookSubscription | None:
        data = await self._store.get(sub_id)
        if data is None:
            return None
        return WebhookSubscription(**data)

    async def list_all(self) -> list[dict[str, Any]]:
        """Все подписки — с локальным кешем 60s для производительности."""
        now = time.monotonic()
        if now - self._cache_updated > self._cache_ttl:
            raw = await self._store.all()
            self._cache = {
                sub_id: WebhookSubscription(**data) for sub_id, data in raw.items()
            }
            self._cache_updated = now
        return [asdict(sub) for sub in self._cache.values()]

    async def find_by_event(self, event_type: str) -> list[WebhookSubscription]:
        """Находит подписки по event_type."""
        all_subs = await self.list_all()
        return [
            WebhookSubscription(**s)
            for s in all_subs
            if s.get("event_type") == event_type and s.get("active", True)
        ]


redis_webhook_registry = RedisWebhookRegistry()
