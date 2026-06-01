"""AI invocation audit schema (ADR-0071, S27 W5).

10 событий ``ai.invocation.*`` для полного traceability AI-вызова:

- ai.invocation.requested       — после _resolve_policy
- ai.invocation.policy_resolved — policy найдена
- ai.invocation.sanitized        — после input sanitizers
- ai.invocation.guarded.input   — после input guards
- ai.invocation.guarded.output   — после output guards
- ai.invocation.completed        — успех
- ai.invocation.denied           — capability/policy denied
- ai.invocation.failed           — error
- ai.invocation.pii.mask         — PII detected + masked
- ai.invocation.pii.unmask        — PII unmasked перед output

События используются для compliance (152-FZ), AI safety audit,
billing и Grafana dashboards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

__all__ = ("AIInvocationEventType", "AIInvocationEvent", "AIInvocationPayload")


class AIInvocationEventType(StrEnum):
    """Типы событий ai.invocation.* (ADR-0071)."""

    REQUESTED = "ai.invocation.requested"
    POLICY_RESOLVED = "ai.invocation.policy_resolved"
    SANITIZED = "ai.invocation.sanitized"
    GUARDED_INPUT = "ai.invocation.guarded.input"
    GUARDED_OUTPUT = "ai.invocation.guarded.output"
    COMPLETED = "ai.invocation.completed"
    DENIED = "ai.invocation.denied"
    FAILED = "ai.invocation.failed"
    PII_MASK = "ai.invocation.pii.mask"
    PII_UNMASK = "ai.invocation.pii.unmask"


class AIInvocationPayload(BaseModel):
    """Payload для ai.invocation.* событий (ADR-0071 §2).

    Все поля опциональны — заполняются по мере прохождения pipeline.
    События создаются с минимально необходимым набором атрибутов
    на каждом шаге.
    """

    # Идентификация вызова
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: AIInvocationEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Контекст вызова
    workflow_id: str | None = None
    tenant_id: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None

    # Policy
    policy_id: str | None = None
    policy_version: int | None = None
    policy_name: str | None = None

    # Модель и токены
    model_used: str | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    cost_usd: float | None = None

    # Guard results
    guard_type: str | None = None
    """Тип guard'а: 'nemo', 'rebuff', 'lakera', 'llama_guard'."""
    guard_verdict: str | None = None
    """Вердикт: 'passed', 'blocked', 'warned'."""
    guard_categories: list[str] = Field(default_factory=list)
    """Срабоавшие категории при блокировке."""

    # PII
    pii_detected: bool | None = None
    pii_entity_types: list[str] = Field(default_factory=list)
    pii_mask_count: int | None = None

    # Sanitizer
    sanitizer_type: str | None = None
    """Тип sanitizer: 'pii_tokenizer', 'presidio'."""
    sanitizer_version: str | None = None

    # Error / Denial
    error_class: str | None = None
    error_message: str | None = None
    denied_reason: str | None = None

    # Metadata
    latency_ms: int | None = None
    extra_attrs: dict[str, str] = Field(default_factory=dict)


class AIInvocationEvent(BaseModel):
    """Единое событие ai.invocation.* для unified audit sink (ADR-0071 §3).

    Используется для записи в ClickHouse и для unified AuditService.
    Данные PII маскируются (mask_irreversible) перед записью.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: AIInvocationEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Mandatory context
    workflow_id: str
    tenant_id: str | None = None
    correlation_id: str | None = None

    # Policy
    policy_name: str | None = None
    policy_version: int = 1

    # Model info (заполняется на завершении)
    model_used: str | None = None
    tokens_total: int | None = None
    cost_usd: float | None = None

    # Guard info
    guard_type: str | None = None
    guard_verdict: str | None = None
    guard_categories: list[str] = Field(default_factory=list)

    # PII
    pii_detected: bool = False
    pii_entity_types: list[str] = Field(default_factory=list)

    # Error
    error_class: str | None = None
    error_message: str | None = None

    # Latency
    latency_ms: int | None = None

    # Extra attrs from policy
    extra_attrs: dict[str, str] = Field(default_factory=dict)

    def with_guard_result(
        self, guard_type: str, verdict: str, categories: list[str]
    ) -> "AIInvocationEvent":
        """Копирует событие с guard result (для guarded.input/output событий)."""
        return self.model_copy(
            update={
                "guard_type": guard_type,
                "guard_verdict": verdict,
                "guard_categories": categories,
            }
        )

    def with_pii_result(
        self, detected: bool, entity_types: list[str]
    ) -> "AIInvocationEvent":
        """Копирует событие с PII result."""
        return self.model_copy(
            update={"pii_detected": detected, "pii_entity_types": entity_types}
        )
