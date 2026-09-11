"""RouteContract — declarative spec + validation (Wave 1 P0 #25)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class BackoffStrategy(str, enum.Enum):
    """Retry backoff strategy."""

    NONE = "none"  # immediate retry
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass(slots=True)
class RetryPolicy:
    """Retry policy для failed operations."""

    max_attempts: int = 3
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    retryable_failure_classes: tuple[str, ...] = ("retryable",)


@dataclass(slots=True)
class IdempotencyPolicy:
    """Idempotency policy для write-операций."""

    key_field: str  # field name в payload для dedupe key
    ttl_seconds: int = 86400
    backend: str = "default"  # backend alias (default/redis/postgres)


@dataclass(slots=True)
class DLQPolicy:
    """DLQ policy для failed events."""

    topic: str
    max_retries: int = 3
    include_payload: bool = True


@dataclass(slots=True)
class RouteContract:
    """Declarative contract для route.

    Attributes:
        route_id: Unique route ID.
        input_schema: JSON Schema для input validation.
        output_schema: JSON Schema для output validation.
        side_effects: list of side effect types ("db_write", "mq_publish", ...).
        timeout_seconds: Hard timeout для всего route execution.
        retry_policy: Retry configuration.
        idempotency_policy: Optional idempotency (None = not idempotent).
        dlq_policy: Optional DLQ (None = drop on failure).
        owner: Team/person responsible.
        slo: Optional SLO dict (latency_p99_ms, availability, error_rate).
        tags: произвольные tags.
        description: human-readable description.

    """

    route_id: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency_policy: IdempotencyPolicy | None = None
    dlq_policy: DLQPolicy | None = None
    owner: str = ""
    slo: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    description: str = ""


# Required fields для PolicyGate (CI enforcement).
_REQUIRED_FIELDS = ("route_id", "timeout_seconds", "owner", "side_effects")


def validate_contract(contract: RouteContract) -> list[str]:
    """Validate RouteContract against PolicyGate.

    Returns:
        List of violation messages (empty if valid).

    PolicyGate rules:
    - route_id: non-empty.
    - timeout_seconds: 0 < timeout <= 300 (SLA-bound).
    - owner: non-empty (no orphan routes).
    - side_effects: non-empty list.
    - Если есть writes → idempotency_policy обязательна.
    - retry_policy.max_attempts: 1 <= max_attempts <= 10.

    """
    errors: list[str] = []

    # route_id.
    if not contract.route_id or not contract.route_id.strip():
        errors.append("route_id is required and non-empty")

    # timeout_seconds.
    if contract.timeout_seconds <= 0:
        errors.append(
            f"timeout_seconds must be > 0 (got {contract.timeout_seconds})"
        )
    elif contract.timeout_seconds > 300:
        errors.append(
            f"timeout_seconds must be <= 300 (SLA-bound, got {contract.timeout_seconds})"
        )

    # owner.
    if not contract.owner or not contract.owner.strip():
        errors.append(
            "owner is required (no orphan routes — assign team/person)"
        )

    # side_effects.
    if not contract.side_effects:
        errors.append(
            "side_effects is required (e.g., ['db_write'], ['mq_publish'], "
            "['read_only'])"
        )

    # Idempotency для writes.
    has_writes = any(
        s in ("db_write", "mq_publish", "file_write", "external_call")
        for s in contract.side_effects
    )
    if has_writes and contract.idempotency_policy is None:
        errors.append(
            "idempotency_policy is required for write routes "
            "(side_effects include db_write/mq_publish/file_write/external_call)"
        )

    # Retry policy sanity.
    if contract.retry_policy.max_attempts < 1:
        errors.append(
            f"retry_policy.max_attempts must be >= 1 (got {contract.retry_policy.max_attempts})"
        )
    elif contract.retry_policy.max_attempts > 10:
        errors.append(
            f"retry_policy.max_attempts must be <= 10 (got {contract.retry_policy.max_attempts})"
        )

    return errors


__all__ = (
    "BackoffStrategy",
    "DLQPolicy",
    "IdempotencyPolicy",
    "RetryPolicy",
    "RouteContract",
    "validate_contract",
)
