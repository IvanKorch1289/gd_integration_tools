"""Sprint 169 Phase B CL13-FIX: extract ``_build_retry_policy`` to break circular import.

Refactoring history:
- Originally defined в ``step_compilers/__init__.py``
- Sprint 169 Phase B CL13 incorrectly added ``from step_compilers import
  _build_retry_policy`` в ``activity.py`` и ``flow.py`` для mypy CL12/CL13.
- Создал circular import: ``__init__`` импортирует ``activity.py`` (→
  tries to import ``_build_retry_policy`` из частично-initialized
  ``step_compilers`` → ImportError при test collection).
- Fix (S169 R-fix): extract function в sibling-module ``_retry.py``, которая
  не зависит от ``step_compilers`` submodules — both ``activity.py``,
  ``flow.py`` и ``__init__.py`` могут import без cyclic dependency.

Per Ponytail: smallest possible refactor, zero behavior change.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.backend.dsl.workflow.spec import RetryPolicy


def _build_retry_policy(
    decl_policy: RetryPolicy | None, default_policy: RetryPolicy | None
) -> Any:
    """Сконструировать ``temporalio.common.RetryPolicy`` из декларации.

    Если decl_policy и default_policy оба ``None`` — возвращает ``None``
    (Temporal SDK применит свои дефолты). Lazy-import temporalio.
    """
    policy = decl_policy or default_policy
    if policy is None:
        return None
    from temporalio.common import RetryPolicy as TemporalRetryPolicy

    kwargs: dict[str, Any] = {
        "initial_interval": timedelta(seconds=policy.initial_interval_s),
        "backoff_coefficient": policy.backoff_coefficient,
        "maximum_attempts": policy.max_attempts,
    }
    if policy.maximum_interval_s is not None:
        kwargs["maximum_interval"] = timedelta(seconds=policy.maximum_interval_s)
    if policy.non_retryable_errors:
        kwargs["non_retryable_error_types"] = list(policy.non_retryable_errors)
    if policy.jitter is not None:
        kwargs["jitter"] = policy.jitter
    return TemporalRetryPolicy(**kwargs)
