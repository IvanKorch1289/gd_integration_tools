"""S68 W2: tests для RetryPolicy (после move в core/ai/).

Проверяют:
1. RetryPolicy доступен через core.ai.retry_policy
2. RetryPolicy backward-compat re-export через dsl.workflow.spec
3. Defaults корректные
4. Constraints (ge, gt, le) enforced
5. extra="forbid" enforced
6. Round-trip serialization
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_retry_policy_importable_from_core_ai() -> None:
    """RetryPolicy доступен через core/ai/retry_policy (новый путь)."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.initial_interval_s == 1.0
    assert policy.backoff_coefficient == 2.0
    assert policy.maximum_interval_s is None
    assert policy.non_retryable_errors == ()
    assert policy.jitter is None


def test_retry_policy_backward_compat_via_dsl() -> None:
    """Backward compat: dsl/workflow/spec re-export'ит RetryPolicy.

    Existing imports ``from src.backend.dsl.workflow.spec import RetryPolicy``
    должны продолжать работать без изменений.
    """
    from src.backend.core.ai.retry_policy import RetryPolicy as CoreRetry
    from src.backend.dsl.workflow.spec import RetryPolicy as DslRetry

    # Один и тот же класс
    assert CoreRetry is DslRetry


def test_retry_policy_defaults() -> None:
    """Все 6 полей имеют default values."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.initial_interval_s == 1.0
    assert policy.backoff_coefficient == 2.0
    assert policy.maximum_interval_s is None
    assert policy.non_retryable_errors == ()
    assert policy.jitter is None


def test_retry_policy_custom_values() -> None:
    """Custom values сохраняются."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    policy = RetryPolicy(
        max_attempts=5,
        initial_interval_s=0.5,
        backoff_coefficient=3.0,
        maximum_interval_s=30.0,
        non_retryable_errors=("ValueError", "KeyError"),
        jitter=0.1,
    )
    assert policy.max_attempts == 5
    assert policy.initial_interval_s == 0.5
    assert policy.backoff_coefficient == 3.0
    assert policy.maximum_interval_s == 30.0
    assert policy.non_retryable_errors == ("ValueError", "KeyError")
    assert policy.jitter == 0.1


def test_retry_policy_max_attempts_must_be_positive() -> None:
    """max_attempts: int >= 1 (ge=1)."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=0)


def test_retry_policy_backoff_must_be_at_least_one() -> None:
    """backoff_coefficient: float >= 1.0 (ge=1.0)."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    with pytest.raises(ValidationError):
        RetryPolicy(backoff_coefficient=0.5)


def test_retry_policy_jitter_bounded() -> None:
    """jitter: 0.0 <= x <= 1.0."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    with pytest.raises(ValidationError):
        RetryPolicy(jitter=1.5)
    with pytest.raises(ValidationError):
        RetryPolicy(jitter=-0.1)


def test_retry_policy_extra_forbid() -> None:
    """extra='forbid' enforced (model_config)."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    with pytest.raises(ValidationError):
        RetryPolicy(unknown_field="x")


def test_retry_policy_serialization_roundtrip() -> None:
    """Round-trip: model_dump → model_validate даёт equal instance."""
    from src.backend.core.ai.retry_policy import RetryPolicy

    original = RetryPolicy(
        max_attempts=4,
        initial_interval_s=2.0,
        backoff_coefficient=2.5,
        maximum_interval_s=60.0,
        non_retryable_errors=("TimeoutError",),
        jitter=0.2,
    )
    dumped = original.model_dump()
    restored = RetryPolicy.model_validate(dumped)
    assert restored == original
