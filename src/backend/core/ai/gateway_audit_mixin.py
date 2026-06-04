"""Audit-контекст и helper'ы для :class:`AIGateway` (ADR-0071).

Извлечено из ``core/ai/gateway.py`` в рамках T-P1.1a (v9 P1 split,
Variant C, maximal scope) для уменьшения god-файла (1091 → ~250 LOC).

Здесь живут:

* :class:`_AuditContext` — dataclass, собирающая данные по мере прохождения
  9-step pipeline и эмитящая события ``ai.invocation.*`` через
  ``audit_service.emit`` (если передан) или
  :func:`emit_ai_invocation_event` (fallback на singleton);
* :func:`_emit_wrapper` — обёртка над ``audit_service.emit`` /
  ``emit_ai_invocation_event`` для backward-compat с тестами.

См. также
--------
* :class:`AIGateway` — :mod:`core.ai.gateway` (ADR-NEW-19);
* :class:`AIInvocationEvent` — :mod:`core.audit.schema.ai_invocation`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.core.ai.errors import GuardResult

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec
    from src.backend.core.audit.schema.ai_invocation import AIInvocationEvent

__all__ = ("_AuditContext", "_emit_wrapper")

logger = logging.getLogger(__name__)


@dataclass
class _AuditContext:
    """Контекст для 9-event audit sequence (ADR-0071 §3).

    Собирает данные по мере прохождения pipeline и эмитит события
    ``ai.invocation.*`` через `audit_service.emit` (если передан) или
    `emit_ai_invocation_event` (fallback на singleton).
    Создаётся в начале :meth:`AIGateway._enforced_invoke`.
    """

    request: AIRequest
    policy: AIPolicySpec | None = None
    policy_name: str = "default"
    input_sanitized: str = ""
    input_pii_detected: bool = False
    input_guard_results: list[GuardResult] = field(default_factory=list)
    rendered: str = ""
    completion: AIResponse | None = None
    output_guard_results: list[GuardResult] = field(default_factory=list)
    final_response: AIResponse | None = None
    model_used: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    # Для тестов: если задан, используется вместо emit_ai_invocation_event
    audit_service: Any = None

    async def _emit(
        self, step: str, *, pii_detected: bool = False, latency_ms: int = 0
    ) -> None:
        """Emit одно событие ``ai.invocation.{step}``."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )

        event_type_map = {
            "requested": AIInvocationEventType.REQUESTED,
            "policy_resolved": AIInvocationEventType.POLICY_RESOLVED,
            "sanitized": AIInvocationEventType.SANITIZED,
            "guarded.input": AIInvocationEventType.GUARDED_INPUT,
            "guarded.output": AIInvocationEventType.GUARDED_OUTPUT,
        }

        event = AIInvocationEvent(
            event_type=event_type_map.get(step, AIInvocationEventType.REQUESTED),
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            pii_detected=pii_detected,
            latency_ms=latency_ms,
        )
        await _emit_wrapper(event, self.audit_service)

    async def _emit_guard(self, step: str, gr: GuardResult) -> None:
        """Emit событие с guard result (guarded.input/output)."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )

        event_type_map = {
            "guarded.input": AIInvocationEventType.GUARDED_INPUT,
            "guarded.output": AIInvocationEventType.GUARDED_OUTPUT,
        }

        event = AIInvocationEvent(
            event_type=event_type_map.get(step, AIInvocationEventType.GUARDED_INPUT),
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            guard_type=gr.guard_name,
            guard_verdict=gr.verdict,
            guard_categories=list(gr.categories),
        )
        await _emit_wrapper(event, self.audit_service)

    async def _emit_final(self, start_ms: int) -> None:
        """Emit завершающее событие: completed / denied / failed."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )

        resp = self.final_response
        if resp is None:
            event_type = AIInvocationEventType.FAILED
            error_class = "InternalError"
            error_message = "No response from pipeline"
        elif resp.guardrails_verdict.get("output") == "blocked":
            event_type = AIInvocationEventType.DENIED
            error_class = "GuardrailBlocked"
            error_message = None
        else:
            event_type = AIInvocationEventType.COMPLETED
            error_class = None
            error_message = None

        total_ms = int(time.monotonic() * 1000) - start_ms
        tokens_total = (resp.tokens_prompt if resp else 0) + (
            resp.tokens_completion if resp else 0
        )

        event = AIInvocationEvent(
            event_type=event_type,
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            model_used=self.model_used or (resp.model_used if resp else None),
            tokens_total=tokens_total,
            cost_usd=resp.cost_usd if resp else None,
            pii_detected=bool(resp.pii_detected if resp else False),
            error_class=error_class,
            error_message=error_message,
            latency_ms=total_ms,
        )

        # Для backward-compat со старыми тестами: вызываем _audit_emit напрямую
        # (в new flow _AuditContext хранит ссылку на gateway для доступа к _audit_service)
        # Этот вызов проходит mock.patch(AIGateway, '_audit_service') в тестах
        # и обеспечивает backward-compat для audit.emit.assert_awaited_once()
        # Новый 9-event path эмитит события через emit_ai_invocation_event
        await _emit_wrapper(event, self.audit_service)


async def _emit_wrapper(event: AIInvocationEvent, audit_service: Any = None) -> None:
    """Обертка для emit — использует переданный audit_service если есть.

    Для backward-compat с тестами: принимает audit_service и вызывает его emit().
    Если не передан — fallback на singleton emit_ai_invocation_event().
    """
    # Приоритет: явно переданный audit_service (для тестов), иначе singleton
    if audit_service is not None:
        try:
            await audit_service.emit(event)
            return
        except Exception as exc:
            logger.debug("AIGateway: audit_service.emit failed: %s", exc)
            return
    # fallback на глобальный singleton
    try:
        from src.backend.core.audit.sinks.ai_unified_sink import (
            emit_ai_invocation_event,
        )

        emit_ai_invocation_event(event)
    except Exception as exc:
        logger.debug("AIGateway: emit_ai_invocation_event failed: %s", exc)
