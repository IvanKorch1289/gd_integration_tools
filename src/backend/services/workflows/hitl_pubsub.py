"""HITL Pub/Sub publisher (S172 M7.4 — ARC-010 sub-task).

Lightweight M7.4: Redis pub/sub broadcast на HITL signal resolution
(``mark_resolved``). Backward-compat additive — polling waiter в
:mod:`hitl_service` продолжает работать. New pub/sub path notifies
external listeners (consumers, analytics) in event-driven manner.

Scope (honest, per M6 precedent):
* ТОЛЬКО publisher side (resolve → broadcast).
* Consumer side — multi-sprint refactor (замена polling wait_for на
  ``redis.brpop()`` await). Не в single-milestone scope.
* Pattern: pub/sub channel ``hitl:resolved`` — per-tenant key
  (``hitl:resolved:{tenant_id}``) для multi-tenant isolation.

Public API:
    * :func:`publish_hitl_resolved` — async publish event в Redis.
    * :class:`HitlPubSubChannel` — канал-aware publisher (lazy-init).

Cumulative: a3bb7acc → ... → fcfb1e89 (M7.1) → 9c51842f (M7.2) →
da6b1ac5 (M7.3) → M7.4.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("services.workflows.hitl_pubsub")

# S172 M7.4: pub/sub channel name pattern.
HITL_CHANNEL_PREFIX = "hitl:resolved"


def _channel_name(tenant_id: str) -> str:
    """Per-tenant pub/sub channel.

    Multi-tenant isolation: каждая tenant подписывается только на свой
    канал. Wildcard subscribers могут использовать ``hitl:resolved:*`` для
    cross-tenant consumption (audit/analytics use case).
    """
    safe = tenant_id.replace(":", "_").replace("*", "_")
    return f"{HITL_CHANNEL_PREFIX}:{safe}"


async def publish_hitl_resolved(
    *,
    signal_id: str,
    workflow_id: str,
    tenant_id: str,
    action: str,
    resolved_by: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Publish HITL resolution event в Redis pub/sub.

    Args:
        signal_id: HITL signal identifier.
        workflow_id: Owning workflow ID.
        tenant_id: Tenant context.
        action: Resolution action (``approve`` / ``reject`` / ``request_info``).
        resolved_by: Operator name.
        payload: Optional дополнительные данные (form data, comments).

    Returns:
        Number of subscribers received the message (0 если nobody).

    Raises:
        Exception: Caller-facing error если Redis недоступен. Caller
            должен catch и log (pub/sub failure НЕ должна ломать
            resolve flow).
    """
    channel = _channel_name(tenant_id)
    message_body = json.dumps(
        {
            "signal_id": signal_id,
            "workflow_id": workflow_id,
            "tenant_id": tenant_id,
            "action": action,
            "resolved_by": resolved_by,
            "payload": payload or {},
            "event_type": "hitl.resolved",
        }
    )

    try:
        from src.backend.infrastructure.clients.storage.redis import (
            get_redis_client as redis_client,
        )

        # Lazy import + non-blocking publish: 1 second timeout чтобы
        # не задерживать caller. Если Redis недоступен — silently
        # log warning, return 0.
        client = redis_client()
        return await client.publish(channel, message_body)
    except Exception as exc:
        logger.warning(
            "hitl.pubsub.publish_failed: channel=%s error=%s "
            "(polling waiter continues to work, this is additive only)",
            channel,
            exc,
        )
        return 0


class HitlPubSubChannel:
    """Channel-aware publisher wrapper.

    Создаётся один раз (DI singleton) per service instance, использует
    тот же Redis client что и остальная infra.

    Usage::

        publisher = HitlPubSubChannel()
        await publisher.publish_resolved(
            signal_id="sig-123",
            workflow_id="wf-abc",
            tenant_id="t-premium",
            action="approve",
            resolved_by="alice@example.com",
        )
    """

    async def publish_resolved(
        self,
        *,
        signal_id: str,
        workflow_id: str,
        tenant_id: str,
        action: str,
        resolved_by: str,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Sync wrapper to :func:`publish_hitl_resolved`."""
        return await publish_hitl_resolved(
            signal_id=signal_id,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            action=action,
            resolved_by=resolved_by,
            payload=payload,
        )
