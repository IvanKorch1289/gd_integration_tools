"""Redis transport для CertStore subscribe_updates (S171 M22, D257).

Pub/Sub-based multi-instance cert invalidation.
Pattern (D257, Ponytail): thin wrapper над redis.asyncio.
"""
# ruff: noqa: E501
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger("security.cert_store.transport_redis")

__all__ = ("RedisCertTransport", "DEFAULT_CHANNEL")

DEFAULT_CHANNEL = "cert:updated"


class RedisCertTransport:
    """Redis Pub/Sub transport для cert store events (D257)."""

    def __init__(
        self,
        *,
        redis_url: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> None:
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Any = None

    def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis_asyncio
        except ImportError as exc:
            raise ImportError(
                "redis не установлен. pip install redis>=5.0"
            ) from exc
        self._redis = redis_asyncio.from_url(
            self._redis_url, decode_responses=True
        )
        return self._redis

    def _format_message(self, cert_id: str, action: str = "set") -> dict[str, Any]:
        return {
            "cert_id": cert_id,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def publish(self, cert_id: str, *, action: str = "set") -> None:
        redis = self._ensure_redis()
        msg = self._format_message(cert_id, action=action)
        redis.publish(self._channel, json.dumps(msg))
        logger.info(
            "cert.transport.redis.publish cert=%s action=%s",
            cert_id, action,
        )

    def subscribe(self) -> Any:
        redis = self._ensure_redis()
        pubsub = redis.pubsub()
        pubsub.subscribe(self._channel)
        return self._listen(pubsub)

    async def _listen(self, pubsub: Any) -> Any:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("cert.transport.redis.decode_error: %s", exc)
                continue
            yield data

    def attach(self, store: Any) -> None:
        from src.backend.infrastructure.security.cert_store.store import (
            CertStore,
        )

        if not isinstance(store, CertStore):
            raise TypeError(
                f"store должен быть CertStore, получен {type(store)}"
            )

        async def on_update(cert_id: str) -> None:
            self.publish(cert_id, action="set")

        store.subscribe_updates(on_update)
        logger.info("cert.transport.redis.attached")
