"""Unified AI audit sink (ADR-0071, S27 W5).

Пишет события ``ai.invocation.*`` в:
1. ClickHouse через AuditService (primary)
2. Langfuse trace (для cost + observability correlation)

 dual-write window: 1 неделя пишем И в legacy, И в unified sink.
 После закрытия window — удалить legacy ClickHouse audit processor.

Feature-flag ``ai_audit_unified_enabled`` (default-OFF) контролирует
активацию unified path.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.audit.schema.ai_invocation import (
    AIInvocationEvent,
    AIInvocationEventType,
)

logger = logging.getLogger(__name__)

__all__ = ("UnifiedAISink", "emit_ai_invocation_event")


class UnifiedAISink:
    """Unified sink для ai.invocation.* событий (ADR-0071 §3).

    Поддерживает dual-write в ClickHouse + Langfuse.
    При ``ai_audit_unified_enabled=False`` — no-op (backward-compat).

    Usage::

        sink = UnifiedAISink(audit_service=AuditService(), langfuse_callback=callback)
        await sink.emit_event(AIInvocationEvent(...))
    """

    def __init__(
        self,
        audit_service: Any | None = None,
        langfuse_callback: Any | None = None,
        enabled: bool = False,
    ) -> None:
        """Инициализация sink.

        Args:
            audit_service: AuditService для ClickHouse writes.
            langfuse_callback: LangfuseCallbackV3 для Langfuse writes.
            enabled: True = unified path active, False = no-op.
        """
        self._audit = audit_service
        self._langfuse = langfuse_callback
        self._enabled = enabled

    async def emit_event(self, event: AIInvocationEvent) -> None:
        """Emit одного ai.invocation.* события.

        Args:
            event: AIInvocationEvent с заполненными полями.
        """
        if not self._enabled:
            return

        # Dual-write: ClickHouse + Langfuse
        await self._emit_clickhouse(event)
        if self._langfuse is not None:
            await self._emit_langfuse(event)

    async def emit_sequence(self, events: list[AIInvocationEvent]) -> None:
        """Emit последовательности событий (для одной инвокации).

        Args:
            events: Список AIInvocationEvent в порядке следования.
        """
        if not self._enabled:
            return

        for event in events:
            await self.emit_event(event)

    async def _emit_clickhouse(self, event: AIInvocationEvent) -> None:
        """Write в ClickHouse через AuditService."""
        if self._audit is None:
            return

        try:
            from src.backend.core.security.pii_tokenizer import PIITokenizer

            pii_mask = PIITokenizer()
        except Exception:  # noqa: BLE001
            pii_mask = None

        # Маскируем PII перед записью
        error_msg = event.error_message
        if pii_mask is not None and error_msg:
            try:
                error_msg = pii_mask.mask_irreversible(error_msg)
            except Exception:  # noqa: BLE001
                pass

        details: dict[str, Any] = {
            "model_used": event.model_used,
            "tokens_total": event.tokens_total,
            "cost_usd": event.cost_usd,
            "guard_type": event.guard_type,
            "guard_verdict": event.guard_verdict,
            "guard_categories": event.guard_categories,
            "pii_detected": event.pii_detected,
            "pii_entity_types": event.pii_entity_types,
            "latency_ms": event.latency_ms,
            "error_class": event.error_class,
            "extra_attrs": event.extra_attrs,
        }

        try:
            await self._audit.emit(
                event=str(event.event_type.value),
                actor=f"tenant:{event.tenant_id}" if event.tenant_id else "system",
                resource=f"ai_workflow:{event.workflow_id}",
                action="invoke",
                outcome=_outcome_from_event_type(event.event_type),
                severity=_severity_from_event_type(event.event_type),
                correlation_id=event.correlation_id,
                tenant_id=event.tenant_id,
                route_name=event.workflow_id,
                details=details,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("UnifiedAISink: ClickHouse write failed: %s", exc)

    async def _emit_langfuse(self, event: AIInvocationEvent) -> None:
        """Write span в Langfuse для trace correlation."""
        if self._langfuse is None:
            return

        try:
            generation_id = getattr(self._langfuse, "_generation_id", None)
            if generation_id is None:
                return

            trace_event = {
                "event_type": str(event.event_type.value),
                "workflow_id": event.workflow_id,
                "guard_type": event.guard_type,
                "guard_verdict": event.guard_verdict,
                "pii_detected": event.pii_detected,
            }

            if hasattr(self._langfuse, "flush"):
                self._langfuse.flush(generation_id, trace_event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("UnifiedAISink: Langfuse write failed: %s", exc)


def _outcome_from_event_type(event_type: AIInvocationEventType) -> str:
    """Map event type to outcome string."""
    if event_type in (
        AIInvocationEventType.COMPLETED,
        AIInvocationEventType.SANITIZED,
        AIInvocationEventType.POLICY_RESOLVED,
        AIInvocationEventType.REQUESTED,
        AIInvocationEventType.GUARDED_INPUT,
        AIInvocationEventType.GUARDED_OUTPUT,
        AIInvocationEventType.PII_MASK,
        AIInvocationEventType.PII_UNMASK,
    ):
        return "success"
    if event_type in (AIInvocationEventType.DENIED, AIInvocationEventType.FAILED):
        return "failure"
    return "success"


def _severity_from_event_type(event_type: AIInvocationEventType) -> str:
    """Map event type to severity string."""
    if event_type in (AIInvocationEventType.DENIED, AIInvocationEventType.FAILED):
        return "error"
    if event_type in (AIInvocationEventType.GUARDED_INPUT, AIInvocationEventType.GUARDED_OUTPUT):
        return "warning"
    return "info"


# ── Convenience function ───────────────────────────────────────────────────────

_unified_sink: UnifiedAISink | None = None


def emit_ai_invocation_event(
    event: AIInvocationEvent,
    *,
    sink: UnifiedAISink | None = None,
) -> None:
    """Convenience function для emit ai.invocation.* события.

    Использует глобальный singleton UnifiedAISink если sink не передан.

    Args:
        event: AIInvocationEvent.
        sink: Опциональный sink (для тестов).
    """
    global _unified_sink

    if sink is None:
        if _unified_sink is None:
            try:
                from src.backend.core.config.features import feature_flags

                enabled = bool(feature_flags.ai_audit_unified_enabled)
            except Exception:  # noqa: BLE001
                enabled = False

            if enabled:
                try:
                    from src.backend.services.ai.gateway.langfuse_callback_v3 import (
                        LangFuseCallbackV3,
                    )
                    from src.backend.services.audit.audit_service import (
                        get_unified_audit_service,
                    )

                    audit = get_unified_audit_service()
                    langfuse = None
                    try:
                        langfuse = LangFuseCallbackV3()
                    except Exception:  # noqa: BLE001
                        pass

                    _unified_sink = UnifiedAISink(
                        audit_service=audit,
                        langfuse_callback=langfuse,
                        enabled=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("UnifiedAISink: init failed: %s", exc)
                    _unified_sink = UnifiedAISink(enabled=False)
            else:
                _unified_sink = UnifiedAISink(enabled=False)

        sink = _unified_sink

    try:
        from src.backend.core.utils.task_registry import get_task_registry

        registry = get_task_registry()
        registry.create_task(
            sink.emit_event(event),
            name=f"audit.emit.{event.event_type.value}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_ai_invocation_event: failed to schedule: %s", exc)
