from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

# ─── Constants & defaults ──────────────────────────────────────────────

_VALID_TYPES: frozenset[str] = frozenset({"invoice", "contract", "receipt", "other"})
_DEFAULT_TYPE: str = "other"
_DEFAULT_THRESHOLD: float = 0.8
_STAGE_REACHED: str = "route"  # final stage label

# Classification keyword map (case-insensitive).
_CLASSIFY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "bill to", "amount due", "invoice number"),
    "contract": ("contract", "agreement", "party a", "party b", "whereas"),
    "receipt": ("receipt", "paid", "thank you for your purchase", "subtotal"),
}

# Default extractors: dict[type] → list[(field_name, regex)].
# Patterns are deliberately permissive to keep confidence ≥ threshold
# on well-formed documents.

class RoutingMixin:
    """pipeline routing (_route) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    def _route(self, result: IDPResult) -> None:
        """Decide HITL vs auto. Mutates ``result`` in place."""
        # Total pattern count for confidence.
        total_patterns = self._pattern_count(result.doc_type)
        if total_patterns == 0:
            # No patterns → confidence is 0 (other / unconfigured type).
            result.confidence = 0.0
        else:
            result.confidence = round(len(result.fields) / total_patterns, 4)
        if result.validation_errors:
            result.needs_hitl = True
            result.auto_processed = False
            return
        if result.confidence >= self._threshold:
            result.needs_hitl = False
            result.auto_processed = True
        else:
            result.needs_hitl = True
            result.auto_processed = False

