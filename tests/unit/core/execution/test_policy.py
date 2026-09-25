"""Meta-test: ExecutionPolicy (audit W8).

Per 25.09 audit W8: «Объединить политики, сейчас распределённые по
middleware/processors/services» в единую typed ``ExecutionPolicy`` модель.

Контракт:
1. Все 10 полей audit spec представлены:
   - tenant_scope, timeout_budget, retry_budget, concurrency_limit,
     idempotency, data_classification, allowed_egress,
     compensation_required, audit_level, cost_budget;
2. Validation правильно работает для boundary values;
3. Factory methods (default, tenant_scoped, sensitive_pii_action)
   возвращают правильные policy variants;
4. Frozen model (immutable).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from src.backend.core.execution.policy import (
    AuditLevel,
    BackoffStrategy,
    CompensationPolicy,
    DataClassification,
    EgressRule,
    ExecutionPolicy,
    IdempotencyPolicy,
    RetryBudget,
    TenantScope,
)


def test_all_10_audit_fields_present() -> None:
    """Audit W8 spec: все 10 полей присутствуют."""
    required_fields = {
        "tenant_scope",
        "timeout_budget",
        "retry_budget",
        "concurrency_limit",
        "idempotency",
        "data_classification",
        "allowed_egress",
        "compensation_required",
        "audit_level",
        "cost_budget_usd",  # alias для cost_budget
    }
    policy = ExecutionPolicy()
    for field_name in required_fields:
        assert hasattr(policy, field_name), f"Missing field: {field_name}"


def test_policy_is_frozen() -> None:
    """Frozen model — нельзя mutate after creation."""
    from pydantic import ValidationError

    policy = ExecutionPolicy()
    with pytest.raises(ValidationError):
        policy.timeout_budget = 999  # type: ignore[misc]


def test_default_policy() -> None:
    """Default factory."""
    policy = ExecutionPolicy.default()
    assert policy.tenant_scope == TenantScope.GLOBAL
    assert policy.timeout_budget == 30
    assert policy.concurrency_limit == 100
    assert policy.idempotency == IdempotencyPolicy.NONE
    assert policy.data_classification == DataClassification.INTERNAL
    assert policy.audit_level == AuditLevel.BASIC
    assert policy.cost_budget_usd == 1.0


def test_tenant_scoped_factory() -> None:
    """Tenant-scoped policy factory."""
    policy = ExecutionPolicy.tenant_scoped("acme_corp")
    assert policy.tenant_scope == TenantScope.TENANT


def test_sensitive_pii_factory() -> None:
    """Sensitive PII policy — strict audit + idempotency + cost."""
    policy = ExecutionPolicy.sensitive_pii_action()
    assert policy.data_classification == DataClassification.SENSITIVE_PII
    assert policy.audit_level == AuditLevel.FULL
    assert policy.compensation_required is True
    assert policy.idempotency == IdempotencyPolicy.REQUIRED
    assert policy.idempotency_ttl_seconds == 3600
    assert policy.cost_budget_usd == 10.0


def test_timeout_budget_validation() -> None:
    """timeout_budget: 1-3600 seconds."""
    # Valid range
    p = ExecutionPolicy(timeout_budget=1)
    assert p.timeout_budget == 1
    p = ExecutionPolicy(timeout_budget=3600)
    assert p.timeout_budget == 3600
    # Invalid range
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionPolicy(timeout_budget=0)
    with pytest.raises(ValidationError):
        ExecutionPolicy(timeout_budget=3601)


def test_retry_budget_validation() -> None:
    """retry_budget: max_attempts 0-10."""
    RetryBudget(max_attempts=0)
    RetryBudget(max_attempts=10)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RetryBudget(max_attempts=11)


def test_egress_rule_validation() -> None:
    """EgressRule.pattern должен быть valid regex."""
    EgressRule(pattern=r"https://api\.example\.com/.*")
    EgressRule(pattern=r"internal-.*")
    # Invalid regex
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EgressRule(pattern=r"[invalid")


def test_egress_rule_compiles_as_regex() -> None:
    """Pattern компилируется как valid regex (используется в middleware matching)."""
    rule = EgressRule(pattern=r"https://api\.acme\.com/.*")
    compiled = re.compile(rule.pattern)
    assert compiled.match("https://api.acme.com/v1/users")
    assert not compiled.match("https://malicious.com/")


def test_compensation_policy_defaults() -> None:
    """CompensationPolicy defaults: required=False, timeout=10s."""
    comp = CompensationPolicy()
    assert comp.required is False
    assert comp.timeout_ms == 10_000


def test_full_policy_with_all_fields() -> None:
    """Policy with all 10 fields explicitly set."""
    policy = ExecutionPolicy(
        tenant_scope=TenantScope.TENANT,
        timeout_budget=60,
        retry_budget=RetryBudget(max_attempts=5, backoff=BackoffStrategy.JITTERED),
        concurrency_limit=200,
        idempotency=IdempotencyPolicy.REQUIRED,
        idempotency_ttl_seconds=600,
        data_classification=DataClassification.CONFIDENTIAL,
        allowed_egress=(
            EgressRule(pattern=r"https://api\.acme\.com/.*"),
            EgressRule(pattern=r"https://internal\.acme\.local/.*"),
        ),
        compensation_required=True,
        compensation=CompensationPolicy(required=True, timeout_ms=30_000),
        audit_level=AuditLevel.FULL,
        cost_budget_usd=5.0,
    )
    assert policy.tenant_scope == TenantScope.TENANT
    assert policy.timeout_budget == 60
    assert policy.retry_budget.max_attempts == 5
    assert policy.retry_budget.backoff == BackoffStrategy.JITTERED
    assert policy.concurrency_limit == 200
    assert policy.idempotency == IdempotencyPolicy.REQUIRED
    assert policy.idempotency_ttl_seconds == 600
    assert policy.data_classification == DataClassification.CONFIDENTIAL
    assert len(policy.allowed_egress) == 2
    assert policy.compensation_required is True
    assert policy.audit_level == AuditLevel.FULL
    assert policy.cost_budget_usd == 5.0


def test_model_extra_forbid() -> None:
    """Per audit: extra fields forbidden (forbid extra='allow' policy)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionPolicy(unknown_field="foo")  # type: ignore[call-arg]
