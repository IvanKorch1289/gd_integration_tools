"""ExecutionPolicy — единая typed модель execution governance (audit W8).

Per 25.09 audit W8: «Объединить политики, сейчас распределённые по
middleware/processors/services»:

    text
    ExecutionPolicy:
      tenant_scope
      timeout_budget
      retry_budget
      concurrency_limit
      idempotency
      data_classification
      allowed_egress
      compensation_required
      audit_level
      cost_budget

    «Политика компилируется в REST/MQ/Temporal/RPA adapters. Это
предотвращает несовпадающее поведение одного action через разные
протоколы».

MVP scope: Pydantic model + базовая валидация + meta-test.
Интеграция с REST/MQ/Temporal/RPA adapters — отдельный sprint.

Поля:
- ``tenant_scope``: ``global | tenant:<id> | capability:<name>``
- ``timeout_budget``: seconds (целое число, 1-3600)
- ``retry_budget``: max attempts (0-10) + backoff strategy
- ``concurrency_limit``: max in-flight requests (1-1000)
- ``idempotency``: required / optional / none + TTL seconds
- ``data_classification``: ``public | internal | confidential | pii | sensitive_pii``
- ``allowed_egress``: list of host patterns (regex)
- ``compensation_required``: bool — требуется ли saga/rollback
- ``audit_level``: ``none | basic | full | debug``
- ``cost_budget``: max USD per call (0.0-1000.0)
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = (
    "AuditLevel",
    "BackoffStrategy",
    "CompensationPolicy",
    "DataClassification",
    "EgressRule",
    "ExecutionPolicy",
    "IdempotencyPolicy",
    "RetryBudget",
    "TenantScope",
)


class TenantScope(str, Enum):
    """Tenant scope policy для action."""

    GLOBAL = "global"  # system-wide, no tenant filter
    ALL_TENANTS = "all_tenants"  # cross-tenant доступ (admin)
    TENANT = "tenant"  # single tenant scope (per-call tenant_id)


class BackoffStrategy(str, Enum):
    """Backoff strategy для retry policy."""

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    JITTERED = "jittered"


class IdempotencyPolicy(str, Enum):
    """Idempotency requirement level."""

    NONE = "none"  # no idempotency required
    OPTIONAL = "optional"  # TTL applies if Idempotency-Key provided
    REQUIRED = "required"  # caller MUST provide Idempotency-Key


class DataClassification(str, Enum):
    """Data sensitivity level (per ADR-044 privacy tiers)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    SENSITIVE_PII = "sensitive_pii"


class AuditLevel(str, Enum):
    """Audit log level."""

    NONE = "none"  # no audit
    BASIC = "basic"  # action + tenant + status
    FULL = "full"  # + payload + response
    DEBUG = "debug"  # full + intermediate state


class EgressRule(BaseModel):
    """Single egress host pattern (regex)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str = Field(min_length=1, max_length=512)
    description: str | None = None

    @field_validator("pattern")
    @classmethod
    def _validate_regex(cls, v: str) -> str:
        """Pattern должен быть валидным regex."""
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern {v!r}: {exc}") from exc
        return v


class RetryBudget(BaseModel):
    """Retry budget: max attempts + backoff strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=3, ge=0, le=10)
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    max_delay_ms: int = Field(default=5_000, ge=0, le=360_000)


class CompensationPolicy(BaseModel):
    """Compensation policy для saga / distributed transactions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required: bool = False
    timeout_ms: int = Field(default=10_000, ge=0, le=600_000)


class ExecutionPolicy(BaseModel):
    """Unified execution policy (audit W8).

    Поля соотнесены с audit spec:
    - tenant_scope: TenantScope
    - timeout_budget: seconds (целое число)
    - retry_budget: RetryBudget
    - concurrency_limit: max in-flight
    - idempotency: IdempotencyPolicy
    - data_classification: DataClassification
    - allowed_egress: list of EgressRule
    - compensation_required: bool (shorthand) + CompensationPolicy (full)
    - audit_level: AuditLevel
    - cost_budget: USD per call (max)

    Examples:
        >>> policy = ExecutionPolicy.default()
        >>> policy.tenant_scope
        <TenantScope.GLOBAL: 'global'>
        >>> policy.timeout_budget
        30
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Per audit W8 fields:
    tenant_scope: TenantScope = TenantScope.GLOBAL
    timeout_budget: int = Field(default=30, ge=1, le=3600)  # seconds
    retry_budget: RetryBudget = Field(default_factory=RetryBudget)
    concurrency_limit: int = Field(default=100, ge=1, le=1000)
    idempotency: IdempotencyPolicy = IdempotencyPolicy.NONE
    idempotency_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    data_classification: DataClassification = DataClassification.INTERNAL
    allowed_egress: tuple[EgressRule, ...] = ()
    compensation_required: bool = False
    compensation: CompensationPolicy = Field(default_factory=CompensationPolicy)
    audit_level: AuditLevel = AuditLevel.BASIC
    cost_budget_usd: float = Field(default=1.0, ge=0.0, le=1000.0)

    @classmethod
    def default(cls) -> "ExecutionPolicy":
        """Default policy для system-wide non-tenant-scoped actions.

        Per audit W8: «Одна policy одинаково применяется REST/MQ/Temporal/RPA».
        Default values соответствуют baseline для большинства actions.
        """
        return cls()

    @classmethod
    def tenant_scoped(cls, tenant_id: str) -> "ExecutionPolicy":
        """Per-tenant scoped policy (для tenant-specific actions).

        Args:
            tenant_id: tenant identifier (произвольная строка).
        """
        return cls(tenant_scope=TenantScope.TENANT)

    @classmethod
    def sensitive_pii_action(cls) -> "ExecutionPolicy":
        """Strict policy для sensitive PII actions (audit, redact, log).

        Per audit W8: «data_classification: pii | sensitive_pii».
        """
        return cls(
            tenant_scope=TenantScope.TENANT,
            data_classification=DataClassification.SENSITIVE_PII,
            audit_level=AuditLevel.FULL,
            compensation_required=True,
            idempotency=IdempotencyPolicy.REQUIRED,
            idempotency_ttl_seconds=3600,
            cost_budget_usd=10.0,
        )
