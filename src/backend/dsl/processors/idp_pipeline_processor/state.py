from __future__ import annotations

import re
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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


class _FieldPattern:
    """Immutable (field name, regex) pair."""

    name: str
    pattern: str
    regex: str  # alias for pattern (used by DEFAULT_EXTRACTORS public API)

    def __init__(self, name: str, pattern: str) -> None:
        self.name = name
        self.pattern = pattern
        self.regex = pattern  # public API: extracted regexes

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)


class IDPResult:
    """Immutable snapshot of one IDP pipeline run.

    Attributes:
        doc_type: Classified or forced document type.
        fields: Extracted field values.
        confidence: ``matched / total_patterns`` in ``[0.0, 1.0]``.
        validation_errors: List of human-readable error messages.
        needs_hitl: ``True`` if HITL is required.
        auto_processed: ``True`` if high-confidence + validation passed.
        stage_reached: Last successfully reached stage label.
    """

    doc_type: str
    fields: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    validation_errors: list[str] = field(default_factory=list)
    needs_hitl: bool = True
    auto_processed: bool = False
    stage_reached: str = "ingest"
