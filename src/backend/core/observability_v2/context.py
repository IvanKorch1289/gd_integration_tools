"""Semantic context для unified observability (Wave 1 P0 #52)."""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = (
    "SemanticContext",
    "get_current_context",
    "reset_current_context",
    "set_current_context",
)


@dataclass(slots=True)
class SemanticContext:
    """Unified semantic context для distributed tracing + business correlation.

    Attributes:
        trace_id: W3C Trace Context trace-id (32 hex chars).
        span_id: W3C Trace Context span-id (16 hex chars).
        correlation_id: Request-level correlation ID (UUID).
        business_keys: Business-level identifiers (order_id, file_id, ...).
        tenant_id: Multi-tenancy ID.
        route_id: Route execution ID.
        user_id: Actor user ID.
        session_id: Session ID.
        attributes: Custom attributes (extensible).
        parent_span_id: For nested spans.

    """

    trace_id: str = ""
    span_id: str = ""
    correlation_id: str = ""
    business_keys: dict[str, str] = field(default_factory=dict)
    tenant_id: str = ""
    route_id: str = ""
    user_id: str = ""
    session_id: str = ""
    parent_span_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new_root(cls, *, correlation_id: str | None = None) -> "SemanticContext":
        """Create new root context (генерирует trace_id, span_id, correlation_id)."""
        return cls(
            trace_id=_generate_trace_id(),
            span_id=_generate_span_id(),
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

    @classmethod
    def new_child(cls, parent: "SemanticContext") -> "SemanticContext":
        """Create child context (новый span_id, parent_span_id=parent.span_id)."""
        return cls(
            trace_id=parent.trace_id,
            span_id=_generate_span_id(),
            correlation_id=parent.correlation_id,
            parent_span_id=parent.span_id,
            business_keys=dict(parent.business_keys),
            tenant_id=parent.tenant_id,
            route_id=parent.route_id,
            user_id=parent.user_id,
            session_id=parent.session_id,
            attributes=dict(parent.attributes),
        )

    def set_business_key(self, key: str, value: str) -> None:
        """Добавить/обновить business key."""
        self.business_keys[key] = value

    def set_attribute(self, key: str, value: Any) -> None:
        """Добавить/обновить custom attribute."""
        self.attributes[key] = value

    def to_dict(self) -> dict[str, Any]:
        """Serialize для передачи через headers/msg metadata."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "correlation_id": self.correlation_id,
            "parent_span_id": self.parent_span_id,
            "tenant_id": self.tenant_id,
            "route_id": self.route_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "business_keys": dict(self.business_keys),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticContext":
        """Deserialize из dict (e.g., из headers)."""
        return cls(
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id", ""),
            correlation_id=data.get("correlation_id", ""),
            parent_span_id=data.get("parent_span_id", ""),
            tenant_id=data.get("tenant_id", ""),
            route_id=data.get("route_id", ""),
            user_id=data.get("user_id", ""),
            session_id=data.get("session_id", ""),
            business_keys=dict(data.get("business_keys", {})),
            attributes=dict(data.get("attributes", {})),
        )


# contextvars для async-safe current context.
_current_context: contextvars.ContextVar[SemanticContext | None] = (
    contextvars.ContextVar("semantic_context", default=None)
)


def get_current_context() -> SemanticContext | None:
    """Get current SemanticContext (или None)."""
    return _current_context.get()


def set_current_context(context: SemanticContext | None) -> contextvars.Token:
    """Set current SemanticContext (returns token для reset)."""
    return _current_context.set(context)


def reset_current_context(token: contextvars.Token) -> None:
    """Reset context to previous (via token)."""
    _current_context.reset(token)


def _generate_trace_id() -> str:
    """Generate W3C trace-id (32 hex chars)."""
    return uuid.uuid4().hex


def _generate_span_id() -> str:
    """Generate W3C span-id (16 hex chars)."""
    return uuid.uuid4().hex[:16]
