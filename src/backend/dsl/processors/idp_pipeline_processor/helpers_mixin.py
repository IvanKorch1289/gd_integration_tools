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

class HelpersMixin:
    """pipeline helpers (_pattern_count + _result_to_dict) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    def _pattern_count(self, doc_type: str) -> int:
        if self._extractors is not None and doc_type in self._extractors:
            return len(self._extractors[doc_type])
        return len(DEFAULT_EXTRACTORS.get(doc_type, []))

    def _result_to_dict(self, result: IDPResult) -> dict[str, Any]:
        return {
            "doc_type": result.doc_type,
            "fields": dict(result.fields),
            "confidence": result.confidence,
            "validation_errors": list(result.validation_errors),
            "needs_hitl": result.needs_hitl,
            "auto_processed": result.auto_processed,
            "stage_reached": result.stage_reached,
        }

