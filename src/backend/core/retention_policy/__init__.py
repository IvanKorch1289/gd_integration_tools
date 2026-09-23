"""Retention Policy Engine — data lifecycle / legal hold (Wave 4 #74).

Проблема:
    Нет единой data lifecycle policy:
    - Некоторые данные нужно хранить N лет (regulatory).
    - Другие — удалять через X дней (GDPR).
    - Некоторые — immutable для legal hold.

Решение:
    ``RetentionPolicyEngine`` — pure-Python policy engine:

    1. ``RetentionPolicy`` — rule (data_type, retention_days, action).
    2. ``RetentionEngine`` — registry + evaluator.
    3. ``evaluate(data_type, age_days)`` → action (keep/delete/anonymize/archive).
    4. ``LegalHold`` — immutable flag (blocks delete).
    5. ``apply_policy(data, data_type, created_at)`` → action.

Использование::

    from src.backend.core.retention_policy import (  # noqa: F401 — re-export
        RetentionEngine, RetentionPolicy, RetentionAction,
    )

    engine = RetentionEngine()
    engine.register(RetentionPolicy(
        data_type="audit_log", retention_days=2555,  # 7 years
        action=RetentionAction.ARCHIVE,
    ))
    engine.register(RetentionPolicy(
        data_type="session_token", retention_days=1,
        action=RetentionAction.DELETE,
    ))

    action = engine.evaluate("audit_log", age_days=3000)
    # → RetentionAction.ARCHIVE
"""

from __future__ import annotations

from src.backend.core.retention_policy.engine import (  # noqa: F401 — re-export
    LegalHold,
    RetentionAction,
    RetentionEngine,
    RetentionPolicy,
    RetentionVerdict,
    get_retention_engine,
)

__all__ = (
    "LegalHold",
    "RetentionAction",
    "RetentionEngine",
    "RetentionPolicy",
    "RetentionVerdict",
    "get_retention_engine",
)
