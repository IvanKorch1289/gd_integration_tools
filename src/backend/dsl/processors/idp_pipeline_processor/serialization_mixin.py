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

class SerializationMixin:
    """spec serialization (to_spec) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    def to_spec(self) -> dict[str, Any] | None:
        """YAML-round-trip spec for IDPPipelineProcessor."""
        return {
            "idp_pipeline": {
                "doc_type": self._doc_type,
                "confidence_threshold": self._threshold,
                "extractors": (
                    {k: list(v) for k, v in self._extractors.items()}
                    if self._extractors
                    else None
                ),
                "validators": list(self._validators) if self._validators else None,
                "hitl_property": self._hitl_property,
                "result_property": self._result_property,
            }
        }

