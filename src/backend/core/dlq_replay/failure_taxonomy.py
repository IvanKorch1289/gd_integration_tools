"""Failure taxonomy — классификация exceptions (Wave 1 P0 #5 baseline).

Базовый класс :class:`FailureClass` и helper :func:`classify_exception`:

    RETRYABLE     — temporary errors (timeout, network) → retry
    POISON        — malformed/corrupted → DLQ immediately
    BUSINESS      — domain validation (4xx logic) → DLQ, no retry
    SECURITY      — auth/authz violation → DLQ + audit, no retry
    SYSTEM        — bug/invariant violation → escalate
"""

from __future__ import annotations

import enum
from typing import Any


class FailureClass(str, enum.Enum):
    """Failure classification для retry/DLQ policy."""

    RETRYABLE = "retryable"
    POISON = "poison"
    BUSINESS = "business"
    SECURITY = "security"
    SYSTEM = "system"


# Type tags, по которым можно быстро классифицировать exception.
_RETRYABLE_TYPES = frozenset({
    "TimeoutError", "ConnectionError", "ConnectionRefusedError",
    "ConnectionResetError", "BrokenPipeError", "OSError",
    "asyncio.TimeoutError",
})

_POISON_TYPES = frozenset({
    "ValueError", "KeyError", "TypeError", "UnicodeDecodeError",
    "json.JSONDecodeError", "pydantic.ValidationError",
})

_BUSINESS_TYPES = frozenset({
    "BadRequestError", "UnprocessableError", "NotFoundError",
})

_SECURITY_TYPES = frozenset({
    "AuthenticationError", "AuthorizationError",
    "PermissionError", "PermissionDeniedError",
})


class FailureTaxonomy:
    """Классификатор exception → FailureClass.

    Использует type name + дополнительные сигналы (status_code, attribute).
    Custom hook: ``add_rule(type_name, failure_class)`` для project-specific.
    """

    def __init__(self) -> None:
        self._custom_rules: dict[str, FailureClass] = {}

    def add_rule(self, type_name: str, failure_class: FailureClass) -> None:
        """Register custom rule для exception type."""
        self._custom_rules[type_name] = failure_class

    def classify(self, exc: BaseException) -> FailureClass:
        """Classify exception → FailureClass."""
        type_name = type(exc).__name__
        module = type(exc).__module__ or ""

        # 1. Custom rules take precedence.
        full_name = f"{module}.{type_name}"
        if type_name in self._custom_rules:
            return self._custom_rules[type_name]
        if full_name in self._custom_rules:
            return self._custom_rules[full_name]

        # 2. Built-in rules.
        if type_name in _SECURITY_TYPES:
            return FailureClass.SECURITY
        if type_name in _BUSINESS_TYPES:
            return FailureClass.BUSINESS
        if type_name in _POISON_TYPES:
            # ValidationError может быть системной (contract violation).
            if "ValidationError" in type_name and "pydantic" in module:
                return FailureClass.POISON
            return FailureClass.POISON
        if type_name in _RETRYABLE_TYPES:
            return FailureClass.RETRYABLE

        # 3. Heuristics — status_code attribute (например, у HTTPError).
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            if status_code in (401, 403):
                return FailureClass.SECURITY
            if status_code in (408, 429, 500, 502, 503, 504):
                return FailureClass.RETRYABLE
            if 400 <= status_code < 500:
                return FailureClass.BUSINESS

        # 4. Default: SYSTEM (unknown error → escalate).
        return FailureClass.SYSTEM


def classify_exception(exc: BaseException) -> FailureClass:
    """Convenience function: default taxonomy classify."""
    return _default_taxonomy.classify(exc)


# Singleton default taxonomy (mutable через add_rule).
_default_taxonomy = FailureTaxonomy()
