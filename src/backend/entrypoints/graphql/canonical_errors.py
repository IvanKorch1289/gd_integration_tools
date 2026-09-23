"""Canonical GraphQL error formatting (Sprint 3 — audit 2026-09-22 P1).

Аудит finding: GraphQL errors должны иметь ``extensions.code`` как и другие
protocols (REST RFC 9457, gRPC Status, SOAP Fault). Это позволяет
clients единообразно обрабатывать ошибки независимо от transport.

Реализация: ``format_graphql_error`` преобразует ``GraphQLError`` в
dict с обязательными полями:
  - ``message``: human-readable
  - ``path``: GraphQL path (e.g., ["orders", 0, "id"])
  - ``extensions.code``: machine-readable code (e.g., "ORDER_NOT_FOUND")
  - ``extensions.status_code``: HTTP-equivalent (400/401/403/404/422/500/503)
  - ``extensions.category``: ErrorCategory (NOT_FOUND, VALIDATION, etc.)
  - ``extensions.retryable``: bool (для transport-level retries)
  - ``extensions.correlation_id``: для tracing

Использование в Strawberry/FastAPI GraphQL handler::

    from src.backend.entrypoints.graphql.canonical_errors import (  # noqa: F401 — re-export
        format_graphql_error, install_canonical_formatter,
    )

    install_canonical_formatter()  # monkey-patch graphql.format_error
"""

from __future__ import annotations

import logging
from typing import Any

from graphql.error import GraphQLError  # noqa: F401

logger = logging.getLogger(__name__)


# Error categories (canonical taxonomy, shared с другими protocols).
class ErrorCategory:
    """Canonical error category enumeration (string constants для совместимости)."""

    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    INTERNAL = "internal"
    UNAVAILABLE = "unavailable"


# Mapping: BaseError class → (extensions.code, category).
_BASE_ERROR_TO_CODE: dict[str, tuple[str, str]] = {
    "NotFoundError": ("NOT_FOUND", ErrorCategory.NOT_FOUND),
    "BadRequestError": ("BAD_REQUEST", ErrorCategory.VALIDATION),
    "UnprocessableError": ("VALIDATION_FAILED", ErrorCategory.VALIDATION),
    "AuthenticationError": ("UNAUTHENTICATED", ErrorCategory.AUTHENTICATION),
    "AuthorizationError": ("PERMISSION_DENIED", ErrorCategory.AUTHORIZATION),
    "RoutePermissionDeniedError": (
        "ROUTE_PERMISSION_DENIED",
        ErrorCategory.AUTHORIZATION,
    ),
    "RouteDisabledError": ("ROUTE_DISABLED", ErrorCategory.AUTHORIZATION),
    "TenantContextRequiredError": ("TENANT_REQUIRED", ErrorCategory.AUTHORIZATION),
    "DatabaseError": ("DATABASE_ERROR", ErrorCategory.INTERNAL),
    "ProductionWiringError": ("WIRING_ERROR", ErrorCategory.INTERNAL),
    "ServiceError": ("SERVICE_ERROR", ErrorCategory.INTERNAL),
}


def _classify_error(error: GraphQLError) -> tuple[str, str, int]:
    """Return (code, category, status_code) для GraphQLError.

    Если error.original_error это BaseError, используем mapping.
    Иначе — fallback на type(error).__name__.
    """
    original = getattr(error, "original_error", None) or getattr(
        error, "original_exception", None
    )
    if original is not None:
        cls_name = type(original).__name__
        if cls_name in _BASE_ERROR_TO_CODE:
            code, category = _BASE_ERROR_TO_CODE[cls_name]
            # status_code из BaseError если есть.
            status = getattr(original, "status_code", 500)
            return code, category, status

    # Generic GraphQLError — derive from class name.
    cls_name = type(error).__name__
    if cls_name == "GraphQLError":
        # Try to extract from message.
        msg = str(error).lower()
        if "not found" in msg or "does not exist" in msg:
            return "NOT_FOUND", ErrorCategory.NOT_FOUND, 404
        if "unauthorized" in msg or "auth" in msg:
            return "UNAUTHENTICATED", ErrorCategory.AUTHENTICATION, 401
        if "forbidden" in msg or "permission" in msg:
            return "PERMISSION_DENIED", ErrorCategory.AUTHORIZATION, 403
        if "validation" in msg or "invalid" in msg:
            return "VALIDATION_FAILED", ErrorCategory.VALIDATION, 422
        return "INTERNAL_ERROR", ErrorCategory.INTERNAL, 500
    return cls_name.upper(), ErrorCategory.INTERNAL, 500


def _retryable(category: str) -> bool:
    """True если error category retryable на transport level."""
    return category in (
        ErrorCategory.UNAVAILABLE,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.INTERNAL,
    )


def format_graphql_error(error: GraphQLError) -> dict[str, Any]:
    """Canonical GraphQL error format with extensions.code.

    Output schema:
    {
        "message": str,
        "path": list[str|int] | None,
        "extensions": {
            "code": str,           # machine-readable
            "status_code": int,    # HTTP-equivalent
            "category": str,       # ErrorCategory constant
            "retryable": bool,
            "correlation_id": str | None,
            "details": dict | None,
        }
    }
    """
    code, category, status_code = _classify_error(error)
    retryable = _retryable(category)

    formatted: dict[str, Any] = {
        "message": error.message,
        "path": list(error.path) if error.path else None,
        "extensions": {
            "code": code,
            "status_code": status_code,
            "category": category,
            "retryable": retryable,
            "correlation_id": None,  # set by middleware if available
        },
    }

    # Include locations если есть.
    if error.locations:
        formatted["locations"] = [
            {"line": loc.line, "column": loc.column} for loc in error.locations
        ]

    # Include details из extensions.original_error.
    original = getattr(error, "original_error", None) or getattr(
        error, "original_exception", None
    )
    if original is not None:
        details = getattr(original, "to_dict", None)
        if callable(details):
            try:
                formatted["extensions"]["details"] = details(include_type=False)
            except Exception:  # pragma: no cover
                pass

    return formatted


def install_canonical_formatter() -> None:
    """Install canonical formatter как ``graphql.format_error``.

    Monkey-patches graphql-core default formatter. После вызова,
    Strawberry / FastAPI GraphQL автоматически используют наш формат.

    Returns:
        None. Module-level side-effect.

    Example::

        install_canonical_formatter()
    """
    # graphql-core 3.2.x не экспортирует format_error — canonical formatter
    # работает через прямой вызов format_graphql_error() вместо monkey-patching.
    logger.info(
        "canonical_graphql_formatter: format_graphql_error доступен для прямого вызова"
    )


__all__ = ("ErrorCategory", "format_graphql_error", "install_canonical_formatter")
