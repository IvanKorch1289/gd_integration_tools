"""Audit sinks (ADR-0071, S27 W5)."""

from __future__ import annotations

__all__ = ("UnifiedAISink", "emit_ai_invocation_event")

from src.backend.core.audit.sinks.ai_unified_sink import (
    UnifiedAISink,
    emit_ai_invocation_event,
)
