"""Resolver: определяет ``dlq_class`` для envelope на основании route manifest (S13 K3 W4).

Используется в DLQ writers (4 транспорта) до записи: заполняет ``dlq_class``
и применяет policy retention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.messaging.dlq_policy import DLQPolicy, DLQPolicyRegistry
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("resolve_policy_for", "resolve_class_for_envelope")


def resolve_class_for_envelope(
    envelope: "DLQEnvelope",
    *,
    route_manifest: Any | None = None,
    dispatch_action_category: str | None = None,
) -> str:
    """Возвращает ``dlq_class`` для envelope.

    Приоритет:
    1. ``route_manifest.dlq.dlq_class`` (explicit override);
    2. ``dispatch_action_category`` — mapping ``financial|analytics``;
    3. ``envelope.dlq_class`` — если уже заполнен (default ``operational``).
    """
    if route_manifest is not None:
        explicit = getattr(getattr(route_manifest, "dlq", None), "dlq_class", None)
        if explicit:
            return str(explicit)
    if dispatch_action_category:
        mapping = {
            "financial": "financial",
            "analytics": "analytics",
            "operational": "operational",
        }
        mapped = mapping.get(dispatch_action_category.lower())
        if mapped:
            return mapped
    return envelope.dlq_class or "operational"


def resolve_policy_for(
    envelope: "DLQEnvelope",
    *,
    registry: "DLQPolicyRegistry",
    route_manifest: Any | None = None,
    dispatch_action_category: str | None = None,
) -> "DLQPolicy":
    """Возвращает :class:`DLQPolicy` для envelope."""
    class_name = resolve_class_for_envelope(
        envelope,
        route_manifest=route_manifest,
        dispatch_action_category=dispatch_action_category,
    )
    return registry.get_or_default(class_name)
