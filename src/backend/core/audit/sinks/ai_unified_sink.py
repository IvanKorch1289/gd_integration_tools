"""Unified AI audit sink (ADR-0071, S27 W5).

Пишет события ``ai.invocation.*`` в:
1. ClickHouse через AuditService (primary)
2. Langfuse trace (для cost + observability correlation)

 dual-write window: 1 неделя пишем И в legacy, И в unified sink.
 После закрытия window — удалить legacy ClickHouse audit processor.

Feature-flag ``ai_audit_unified_enabled`` (default-OFF) контролирует
активацию unified path.

Layer-correct placement
---------------------
``core/audit/sinks/`` не импортирует ``services/`` напрямую.
Импорт backends (``AuditService``, ``LangFuseCallbackV3``) — в
``services.audit.unified_sink_factory``. Registry-функция
``register_emit_ai_invocation_event`` регистрирует имплементацию
при импорте ``services.audit.unified_sink_factory``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.audit.schema.ai_invocation import (
    AIInvocationEvent,
    AIInvocationEventType,
)
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.audit.interfaces import AuditBackend, LangfuseCallbackBackend

logger = get_logger(__name__)

__all__ = (
    "UnifiedAISink",
    "emit_ai_invocation_event",
    "register_emit_ai_invocation_event",
)


# ── Registry для layer-correct services-имплементации ────────────────────────
# core/audit/sinks не импортирует services/ напрямую.
# services.audit.unified_sink_factory регистрирует имплементацию при импорте.
# Это позволяет core/ai/gateway вызывать emit без импорта из services/.

_emit_fn: Callable[..., Any] | None = None


def register_emit_ai_invocation_event(fn: Callable[..., Any]) -> None:
    """Регистрирует emit-функцию из services/.

    Вызывается ``services.audit.unified_sink_factory`` при импорте.
    После регистрации ``emit_ai_invocation_event`` делегирует в ``fn``.
    """
    global _emit_fn
    _emit_fn = fn


def emit_ai_invocation_event(event: AIInvocationEvent) -> None:
    """Emit ai.invocation.* события.

    До регистрации (early bootstrap) — no-op.
    После регистрации ``services/audit/unified_sink_factory`` — использует singleton.
    """
    if _emit_fn is not None:
        _emit_fn(event)


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
        audit_service: AuditBackend | None = None,
        langfuse_callback: LangfuseCallbackBackend | None = None,
        enabled: bool = False,
    ) -> None:
        """Инициализация sink.

        Args:
            audit_service: AuditBackend для ClickHouse writes.
            langfuse_callback: LangfuseCallbackBackend для Langfuse writes.
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
        """Write в ClickHouse через AuditBackend."""
        if self._audit is None:
            return

        try:
            from src.backend.core.security.pii_tokenizer import PIITokenizer

            pii_mask = PIITokenizer()
        except Exception as _:
            pii_mask = None

        error_msg = event.error_message
        if pii_mask is not None and error_msg:
            try:
                error_msg = pii_mask.mask_irreversible(error_msg)
            except Exception as _:
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
        except Exception as exc:
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
        except Exception as exc:
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
    if event_type in (
        AIInvocationEventType.GUARDED_INPUT,
        AIInvocationEventType.GUARDED_OUTPUT,
    ):
        return "warning"
    return "info"
